#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选时间轴版本横向评测 —— 用音轨发声段做硬真值。

## 判据（比"到最近起音的距离"更硬）

「到最近强起音的距离」有系统性偏差：强起音只有 111 个（70 分位阈值），
而全曲 294 字；连音、拖腔里的字本来就远离任何起音，不代表字幕不同步。

真正硬的判据是**字必须落在人声发声段内**：
  ① 落静音率 —— 落在 F0 断裂（换气/间隙）里的字，字幕必定错位
  ② 跨静音字数 —— 相邻两字之间隔着一段静音，说明中间有字该移位
  ③ 首尾字距 —— 句首字到该句真实音节起点、句尾字到该句真实音节终点

评测对象：本地旧版 / v8 / v9 / 纯官方 TTML。
"""
import argparse
import difflib
import io
import json
import re
import sys

import numpy as np

sys.path.insert(0, ".")
from realign_mid import clean_f0, features, load_audio, sm  # noqa

AUDIO = "separated/htdemucs/song/vocals.wav"
TTML = "work/qrc/song.ttml"


def _ts(s):
    mm = re.search(r"(\d+):(\d+(?:\.\d+)?)", s)
    return float(mm.group(1)) * 60 + float(mm.group(2))


def parse_ttml(path):
    t = io.open(path, encoding="utf-8").read()
    body = t.split("<body", 1)[1]
    out = []
    for pm in re.finditer(r'<p\b([^>]*)>(.*?)</p>', body, re.S):
        for sp in re.finditer(r'<span\b([^>]*)>(.*?)</span>', pm.group(2), re.S):
            sb = re.search(r'\bbegin="([^"]+)"', sp.group(1))
            if not sb:
                continue
            b = _ts(sb.group(1))
            e = b
            se = re.search(r'\bend="([^"]+)"', sp.group(1))
            if se:
                e = _ts(se.group(1))
            for ch in re.sub(r"<[^>]+>", "", sp.group(2)):
                if ch.strip():
                    out.append((ch, b, e))
    return out


class Track:
    def __init__(self, path):
        self.x, self.t = load_audio(path, 0.0, 400.0)
        e, f0, tt = features(self.x)
        self.en = sm(e, 9)
        f0c = clean_f0(f0)
        self.f0m = np.where(f0c > 0, sm(f0c, 5), 0.0)
        self.tt = tt
        self.dt = tt[1] - tt[0]
        self.segments = self._segments()
        self.onsets = self._onsets()

    def _segments(self):
        v = self.f0m > 0
        runs, s0 = [], None
        for i in range(len(v)):
            if v[i] and s0 is None:
                s0 = i
            elif not v[i] and s0 is not None:
                if (i - s0) * self.dt >= 0.05:
                    runs.append((s0, i))
                s0 = None
        if s0 is not None:
            runs.append((s0, len(v)))
        merged = []
        for p, q in runs:
            q = min(q, len(self.tt) - 1)
            if merged and (p - merged[-1][1]) * self.dt < 0.05:
                merged[-1] = (merged[-1][0], q)
            else:
                merged.append((p, q))
        return [(float(self.tt[p]), float(self.tt[q])) for p, q in merged]

    def _onsets(self):
        dn = np.diff(self.en, prepend=self.en[0])
        dn = dn / (np.percentile(np.abs(dn), 99) or 1.0)
        cands = []
        i, n = 1, len(dn)
        while i < n - 1:
            if dn[i] > 0.15 and dn[i] >= dn[i - 1] and dn[i] > dn[i + 1]:
                w = int(0.07 / self.dt)
                pre = self.en[max(0, i - w):i]
                if len(pre):
                    cands.append((float(self.tt[i]), float(self.en[i] - pre.min())))
                i += int(0.07 / self.dt)
                continue
            i += 1
        if not cands:
            return np.array([])
        arr = np.array(cands)
        thr = float(np.percentile(arr[:, 1], 70))
        return np.array(sorted(set(arr[arr[:, 1] >= thr][:, 0])))

    def in_voiced(self, tv, tol=0.04):
        for s0, s1 in self.segments:
            if s0 - tol <= tv <= s1 + tol:
                return True
        return False

    def gap_cover(self, a, b):
        """区间 [a,b] 覆盖的静音总长。"""
        tot = 0.0
        for s0, s1 in self.segments:
            lo, hi = max(a, s0), min(b, s1)
            if hi > lo:
                tot += hi - lo
        return max(0.0, (b - a) - tot)

    def dist_onset(self, tv):
        if len(self.onsets) == 0:
            return 9.9
        k = int(np.searchsorted(self.onsets, tv))
        best = 9.9
        for j in (k - 1, k):
            if 0 <= j < len(self.onsets):
                best = min(best, abs(self.onsets[j] - tv))
        return float(best)

    def nearest_onset(self, tv, max_d=0.40):
        if len(self.onsets) == 0:
            return None
        k = int(np.searchsorted(self.onsets, tv))
        best, bd = None, 1e9
        for j in (k - 1, k, k + 1):
            if 0 <= j < len(self.onsets):
                dd = abs(self.onsets[j] - tv)
                if dd < bd:
                    bd, best = dd, float(self.onsets[j])
        if best is not None and bd <= max_d:
            return best
        return None


def build_official(base, off):
    """纯官方版时间轴：逐字官方 begin + d。"""
    lseq = []
    for li, ln in enumerate(base):
        for ci, ch in enumerate(ln["text"]):
            if ch.strip():
                lseq.append((ch, li, ci))
    sa = "".join(c[0] for c in lseq)
    sb = "".join(c[0] for c in off)
    p2o = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, sa, sb, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                p2o[i1 + k] = j1 + k
    out = []
    for li, ln in enumerate(base):
        idxs = [i for i, c in enumerate(lseq) if c[1] == li]
        nz = [i for i, ch in enumerate(ln["text"]) if ch.strip()]
        full = [0.0] * len(ln["text"])
        ti = 0
        for i in idxs:
            j = p2o.get(i)
            if j is None:
                continue
            full[nz[ti]] = off[j][1]
            ti += 1
        rec = dict(ln)
        rec["times"] = [round(float(v), 3) for v in full]
        out.append(rec)
    return out


def evaluate(name, lines, tr):
    allt, allgap = [], []
    n_silent = n_span = 0
    head_d, tail_d = [], []
    worst = []
    for li, ln in enumerate(lines):
        nz = [i for i, ch in enumerate(ln["text"]) if ch.strip()]
        ts = [float(ln["times"][i]) for i in nz]
        if not ts:
            continue
        allt.extend(ts)
        for u, v in zip(ts, ts[1:]):
            g = tr.gap_cover(u, v)
            if g > 0.12:
                n_span += 1
                allgap.append(g)
        n_silent += sum(1 for v in ts if not tr.in_voiced(v, 0.05))
        h = tr.nearest_onset(ts[0])
        t = tr.nearest_onset(ts[-1])
        if h is not None:
            head_d.append(abs(h - ts[0]))
        else:
            head_d.append(9.9)
            worst.append((li, "首字无起音", round(ts[0], 3)))
        if t is not None:
            tail_d.append(abs(t - ts[-1]))
        else:
            tail_d.append(9.9)
            worst.append((li, "尾字无起音", round(ts[-1], 3)))
    N = len(allt)
    print("\n【%s】%d 字 / %d 句" % (name, N, len(lines)))
    print("  ① 落静音字        : %3d / %d  (%.1f%%)" % (n_silent, N, 100.0 * n_silent / N))
    print("  ② 相邻字跨静音    : %3d 处，跨静音总长 %.2fs" % (n_span, sum(allgap)))
    print("  ③ 句首字距起音    : 均 %.3f  最大 %.3f" % (np.mean(head_d), np.max(head_d)))
    print("     句尾字距起音    : 均 %.3f  最大 %.3f" % (np.mean(tail_d), np.max(tail_d)))
    d = np.array([tr.dist_onset(v) for v in allt])
    print("  ④ 到最近起音距离  : ≤0.12s %3d (%.0f%%)  ≤0.30s %3d (%.0f%%)  均 %.3f"
          % ((d <= 0.12).sum(), 100.0 * (d <= 0.12).mean(),
             (d <= 0.30).sum(), 100.0 * (d <= 0.30).mean(), d.mean()))
    if worst:
        print("     无起音锚点句    : %s" % worst[:8])
    return dict(name=name, silent=n_silent, span=n_span,
                head=float(np.mean(head_d)), tail=float(np.mean(tail_d)),
                hit12=int((d <= 0.12).sum()), hit30=int((d <= 0.30).sum()),
                mean=float(d.mean()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="out/lines.json")
    ap.add_argument("--ttml", default=TTML)
    a = ap.parse_args()
    base = json.load(io.open(a.base, encoding="utf-8"))
    off = parse_ttml(a.ttml)
    tr = Track(AUDIO)

    cands = []
    for nm, path in [("A 本地旧版 anchor", "out/lines_anchor.json"),
                     ("B v8 混合版", "out/lines_sync_v2.json"),
                     ("C v9 混合版", "out/lines_sync_v3.json"),
                     ("E v10 官方骨架", "out/lines_sync_v4.json"),
                     ("F v11 段起点校正", "out/lines_sync_v5.json")]:
        try:
            cands.append((nm, json.load(io.open(path, encoding="utf-8"))))
        except Exception as ex:
            print("跳过 %s：%s" % (path, ex))
    cands.append(("D 纯官方 TTML", build_official(base, off)))

    print("=" * 68)
    for nm, arr in cands:
        evaluate(nm, arr, tr)
    print("=" * 68)


if __name__ == "__main__":
    main()
