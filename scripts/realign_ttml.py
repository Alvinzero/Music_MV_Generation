#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐字时间轴重排 —— 纯官方 TTML 骨架 + 落静音修正 + 首尾字吸附。

## 为什么放弃「逐字择优混合本地旧值」

v8/v9 都用「官方 vs 本地，谁更贴起音用谁」逐字混合。这在句级是错的：
本地旧版在 1:20–1:40 整句偏早 2.5–3.6s，但它**字与字的间距**恰好和起音分布
对得上，于是逐字择优会把官方字换成偏早的本地字 —— 句内节奏被撕裂。

例（句18「你会微笑放手」）：
    官方  88.140 88.490 89.670 90.020 91.200 91.580
    本地  85.380 86.344 87.528 88.544 89.686 90.112
    择优结果 88.03  88.47  87.53(本地!) ...   ← 字3 被拉到句首之前

## v10 规则

  R0 骨架 = 官方 TTML 逐字 begin（d=0，见下）
  R1 句首字 = 吸附到**最近**的强起音（窗口 ±0.25s），无起音则保持官方
  R2 句尾字 = 吸附到**最近**的强起音（窗口 ±0.25s），无起音则保持官方
     —— 拖腔长音的尾巴后面本来就没有起音，保持官方位置才对
     —— v8 用「窗口内最后一个起音」当尾字，把拖腔尾巴提前了 0.5–0.9s，这是错的
  R3 中间字 = 保持官方相对节奏；只有**落进静音**的字才修正
     修正方向：若后面 0.30s 内有发声段起点 → 钉到该起点；
               否则若前面 0.30s 内有发声段终点 → 钉到该终点；
               否则保持原值（强行拉会造成更大错）
  R4 单调递增 + 最小间隔（约束最后生效）

## d = 0 的证据

逐句首尾字直接核对音轨强起音（不是离散命中计数）：
    句15 首 71.930 ↔ 71.925 (0.005)   句17 首 82.240 ↔ 82.220 (0.020)
    句16 字2 77.039 ↔ 77.040 (0.001)   句17 尾 85.530 ↔ 85.580 (0.050)
    句19 首 94.830 ↔ 94.825 (0.005)    句19 尾 97.950 ↔ 97.985 (0.035)

→ 官方 TTML 与本地音轨是同一条录音，零偏移。
（v8 的 d=-0.065 来自「≤0.12s 命中数」这个离散指标，被量化带偏了。）

## 不动的东西
字幕排版（落上/落下、字号、镜号）、动画参数（fad 110/160、move 210）
"""
import argparse
import difflib
import os
import io
import json
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from realign_mid import clean_f0, features, load_audio, sm  # noqa

AUDIO = "separated/htdemucs/song/vocals.wav"
TTML = "work/qrc/song.ttml"


def _ts(s):
    mm = re.search(r"(\d+):(\d+(?:\.\d+)?)", s)
    return float(mm.group(1)) * 60 + float(mm.group(2))


def parse_ttml(path):
    """逐字 (char, begin, end)。官方 TTML 是每字一个 span。"""
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

    # -- 查询
    def in_voiced(self, tv, tol=0.04):
        for s0, s1 in self.segments:
            if s0 - tol <= tv <= s1 + tol:
                return True
        return False

    def dist_onset(self, tv):
        if len(self.onsets) == 0:
            return 9.9
        k = int(np.searchsorted(self.onsets, tv))
        best = 9.9
        for j in (k - 1, k):
            if 0 <= j < len(self.onsets):
                best = min(best, abs(self.onsets[j] - tv))
        return float(best)

    def nearest_onset(self, tv, max_d=0.25):
        """最近起音（**最近**，不是窗口内第一个/最后一个）。"""
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

    def fix_silent(self, tv, win=0.30):
        """落静音的字 → 钉到邻近发声段的起点（优先）或终点。"""
        if self.in_voiced(tv, 0.05):
            return tv, False
        # 后面 win 内有发声段起点 → 钉到起点
        cands = [(s0, 0) for s0, s1 in self.segments if 0 < s0 - tv <= win]
        if cands:
            return min(cands)[0], True
        # 前面 win 内有发声段终点 → 钉到终点
        cands = [(s1, 1) for s0, s1 in self.segments if 0 < tv - s1 <= win]
        if cands:
            return min(cands, key=lambda x: x[0])[0], True
        return tv, False


def enforce(times, gap_min):
    """单调递增 + 最小间隔。"""
    t = np.array(times, dtype=float)
    if len(t) == 0:
        return t
    t = np.maximum.accumulate(t)
    for k in range(len(t) - 2, -1, -1):
        t[k] = min(t[k], t[k + 1] - gap_min)
    for k in range(1, len(t)):
        if t[k] < t[k - 1] + gap_min:
            t[k] = t[k - 1] + gap_min
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default=AUDIO)
    ap.add_argument("--ttml", default=TTML)
    ap.add_argument("--lines", default="out/lines_anchor.json")
    ap.add_argument("--base", default="out/lines.json")
    ap.add_argument("--out", default="out/lines_sync_v4.json")
    ap.add_argument("--report", default="out/sync_report_v4.json")
    ap.add_argument("--min-gap", type=float, default=0.085)
    ap.add_argument("--snap-win", type=float, default=0.25)
    a = ap.parse_args()

    lines = json.load(io.open(a.lines, encoding="utf-8"))
    base = json.load(io.open(a.base, encoding="utf-8"))
    tr = Track(a.audio)
    print("音轨：发声段 %d，强起音 %d\n" % (len(tr.segments), len(tr.onsets)))

    # ---- 字级对应
    lseq = []
    for li, ln in enumerate(base):
        for ci, ch in enumerate(ln["text"]):
            if ch.strip():
                lseq.append((ch, li, ci))
    off = parse_ttml(a.ttml)
    sa = "".join(c[0] for c in lseq)
    sb = "".join(c[0] for c in off)
    p2o = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, sa, sb, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                p2o[i1 + k] = j1 + k
    print("字符级对应 %d / %d\n" % (len(p2o), len(sa)))

    # ---- d：首尾字 vs 最近起音 的中位数
    dv = []
    for li, ln in enumerate(base):
        idxs = [i for i, c in enumerate(lseq) if c[1] == li]
        ots = [off[p2o[i]][1] if i in p2o else None for i in idxs]
        if any(v is None for v in ots) or not ots:
            continue
        for v in (ots[0], ots[-1]):
            o = tr.nearest_onset(v, 0.30)
            if o is not None:
                dv.append(o - v)
    d = float(np.median(dv)) if dv else 0.0
    print("d（中位数）= %+.4f  样本 %d\n" % (d, len(dv)))

    # ---- 逐句
    print("%-3s %-18s %-7s %7s %7s %6s %6s  %s"
          % ("句", "文本", "修正", "首距", "尾距", "≤.12", "≤.30", "逐字"))
    result, report = [], []
    n_snap = n_fix = 0
    for li, ln in enumerate(lines):
        idxs = [i for i, c in enumerate(lseq) if c[1] == li]
        nz = [i for i, ch in enumerate(ln["text"]) if ch.strip()]
        ots = [off[p2o[i]][1] if i in p2o else None for i in idxs]
        if any(v is None for v in ots) or len(ots) != len(nz):
            result.append(dict(ln))
            report.append({"line": li, "text": ln["text"], "note": "无官方对应，沿用本地"})
            print("%-3d %-18s %-7s (无官方对应，沿用本地)" % (li, ln["text"][:16], "-"))
            continue

        ot = [float(v) + d for v in ots]
        times = list(ot)
        flags = [""] * len(ot)

        # R3 中间字：落静音的修正
        for i in range(1, len(times) - 1):
            tv, fixed = tr.fix_silent(times[i])
            if fixed:
                times[i] = tv
                flags[i] = "S"
                n_fix += 1

        # R1/R2 首尾字：吸附到最近的强起音
        h = tr.nearest_onset(times[0], a.snap_win)
        if h is not None and abs(h - times[0]) > 1e-6:
            times[0] = h
            flags[0] = "H"
            n_snap += 1
        t_ = tr.nearest_onset(times[-1], a.snap_win)
        if t_ is not None and abs(t_ - times[-1]) > 1e-6:
            times[-1] = t_
            flags[-1] = "T"
            n_snap += 1

        # R2b 吸附后若落进静音 → 推到最近的发声段起点
        #     （强起音有时正好压在拖腔结束的静音边界上，如 64.240 / 145.255）
        for i in range(len(times)):
            if not tr.in_voiced(times[i], 0.05):
                tv, fixed = tr.fix_silent(times[i])
                if fixed:
                    times[i] = tv
                    flags[i] = (flags[i] or "") + "S"
                    n_fix += 1

        # R4 约束（最后生效）
        ogap = (ot[-1] - ot[0]) / max(1, len(ot) - 1)
        gap_min = max(a.min_gap, 0.42 * ogap)
        times = enforce(times, gap_min)

        d12 = np.array([tr.dist_onset(v) for v in times])

        # 回填（含空格位）
        full = [0.0] * len(ln["text"])
        ti = 0
        for ci in range(len(ln["text"])):
            if ln["text"][ci].strip():
                full[ci] = float(times[ti]); ti += 1
            else:
                full[ci] = float(times[max(0, ti - 1)]) if ti else float(times[0])

        new = dict(ln)
        new["times"] = [round(float(v), 3) for v in full]
        new["fit"] = "official-v10"
        result.append(new)
        report.append({
            "line": li, "text": ln["text"], "flags": "".join(flags),
            "first_dist": round(float(d12[0]), 4),
            "last_dist": round(float(d12[-1]), 4),
            "hit12": int((d12 <= 0.12).sum()), "hit30": int((d12 <= 0.30).sum()),
            "n": len(times),
            "new_times": [round(float(v), 3) for v in times],
            "off_times": [round(float(v), 3) for v in ot],
        })
        print("%-3d %-18s %-7s %7.3f %7.3f %3d/%-3d %3d/%-3d  %s"
              % (li, ln["text"][:16], "".join(flags) or "-",
                 d12[0], d12[-1],
                 int((d12 <= 0.12).sum()), len(times),
                 int((d12 <= 0.30).sum()), len(times),
                 " ".join("%.2f" % v for v in times)))

    # ---- 统计
    allnew = [x for r in report if "new_times" in r for x in r["new_times"]]
    dn = np.array([tr.dist_onset(v) for v in allnew])
    print("\n== 全曲 %d 字 ==" % len(dn))
    print("  ≤0.12s %3d (%.0f%%)  ≤0.30s %3d (%.0f%%)  均距 %.3f"
          % ((dn <= 0.12).sum(), 100.0 * (dn <= 0.12).mean(),
             (dn <= 0.30).sum(), 100.0 * (dn <= 0.30).mean(), dn.mean()))
    print("  首尾吸附 %d 次，落静音修正 %d 次" % (n_snap, n_fix))

    # ---- 质量守门
    collapse, biggap = [], []
    for r in report:
        if "new_times" not in r:
            continue
        ts_ = r["new_times"]
        if len(set(round(v, 2) for v in ts_)) < len(ts_):
            collapse.append(r["line"])
        for u, v in zip(ts_, ts_[1:]):
            if v - u > 1.5:
                biggap.append((r["line"], round(v - u, 3)))
    print("\n质量守门：")
    print("  同刻塌缩句：%s" % (collapse if collapse else "无"))
    print("  >1.5s 异常间隔：%s" % (biggap if biggap else "无"))

    # ---- 句子边界
    for i in range(len(result)):
        nzm = [k for k, ch in enumerate(result[i]["text"]) if ch.strip()]
        result[i]["start_new"] = round(float(result[i]["times"][nzm[0]]), 3)
        if i + 1 < len(result):
            nzn = [k for k, ch in enumerate(result[i + 1]["text"]) if ch.strip()]
            result[i]["end_new"] = round(float(result[i + 1]["times"][nzn[0]]), 3)
        else:
            result[i]["end_new"] = round(float(result[i]["times"][-1] + 0.4), 3)

    json.dump(result, io.open(a.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(report, io.open(a.report, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n写入 %s / %s" % (a.out, a.report))


if __name__ == "__main__":
    main()
