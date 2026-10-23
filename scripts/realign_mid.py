#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频特征提取与诊断工具（F0 发声段 / 能量起音 / 音节切分）。

## 根因（三条独立证据交叉确认）

1. **F0 音节切分**：人声轨在 80.42–82.09 有 1.67s 完全无声，但当前版本把「的」放在
   81.744 —— 落在静音里。87.53 附近的「微」同样落在 87.10–87.54 的静音里。
2. **官方 TTML**（amll-ttml-db，id 001qvvgF38HVc4）：「过」被拖成 3.23s 长音，
   「挽留的话」整块从 82.24 才开始；「你会微笑放手」整块从 88.14 才开始。
   本地版本把这三句的首字分别放在 79.63 / 85.38 / 91.25 —— **整体早了约 2.5s**。
3. **副歌重复段**：同一段旋律在 2:18 与 1:20 各出现一次，两处歌词句首相同，
   官方 TTML 给出的句内结构完全一致，可以互相印证。

## 为什么会错

`realign_anchor.py` 的 `place_line()` 用「句内第一个能量导数峰」当首字锚点。
但在 拖腔密集的段落，**上一句的尾音被拖长**（「过」拖 3.2s），拖长段里还有好几个
能量起伏。检测器把拖长段里的起伏当成了新句的起音，于是首字被提前了 2.5s，
后面所有字跟着整体错位。

## 修复方案

不用官方 TTML 的绝对时间（那是另一版混音，绝对时间对不上），而是：
1. 用**官方 TTML 的句内相对结构**确定每句应该有几个字落在哪个相对位置；
2. 用**我们自己人声轨的 F0 音节边界**把每一句的真实音节切出来；
3. 首字钉在**该句的第一个真实音节**上，尾字钉在**最后一个真实音节**上；
4. 中间的字按累积实唱时长分配，并吸附到真实音节边界。
"""
import argparse
import io
import os
import json
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SR, HOP, NFFT = 16000, 80, 1024


# ---------------------------------------------------------------- 音频特征
def load_audio(path, lo, hi):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    t = np.arange(len(x)) / SR
    m = (t >= lo) & (t < hi)
    return x[m], t[m]


def features(x):
    win = np.hanning(NFFT).astype(np.float32)
    n = 1 + (len(x) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    fr = x[idx] * win
    S = np.abs(np.fft.rfft(fr, axis=1)) ** 2
    f = np.fft.rfftfreq(NFFT, 1.0 / SR)
    band = (f >= 70) & (f <= 900)
    e = np.log1p(np.sqrt(S[:, band].sum(1)))
    f0 = np.zeros(n)
    for i in range(n):
        seg = fr[i]
        r = np.correlate(seg, seg, "full")[NFFT - 1:]
        if r[0] <= 0:
            continue
        lo_l, hi_l = SR // 500, SR // 70
        sr = r[lo_l:hi_l]
        if len(sr) < 3:
            continue
        k = int(np.argmax(sr))
        if sr[k] / r[0] > 0.35:
            f0[i] = SR / (lo_l + k)
    return e, f0, np.arange(n) * HOP / SR


def sm(v, k):
    if k <= 1 or len(v) < k:
        return v
    return np.convolve(v, np.ones(k) / k, mode="same")


def clean_f0(f0):
    """中值滤波 + 八度纠错。"""
    valid = f0 > 0
    if not valid.any():
        return f0
    fi = np.interp(np.arange(len(f0)), np.where(valid)[0], f0[valid])
    w = 21
    pad = np.pad(fi, (w // 2, w // 2), mode="edge")
    out = np.array([np.median(pad[i:i + w]) for i in range(len(fi))])
    out = np.where(valid, out, 0.0)
    gm = np.median(out[out > 0]) or 1.0
    for i in range(len(out)):
        if out[i] <= 0:
            continue
        for k in (2.0, 0.5, 4.0, 0.25):
            if abs(out[i] / gm - k) < 0.12:
                out[i] /= k
                break
    return out


def voiced_segments(e, tt, floor_ratio=0.20):
    """能量过门限的连续发声段 —— 就是「人在唱」的时间段。"""
    base = float(np.percentile(e, 4))
    peak = float(np.percentile(e, 97))
    thr = base + floor_ratio * (peak - base)
    v = e > thr
    runs, s0 = [], None
    for i in range(len(v)):
        if v[i] and s0 is None:
            s0 = i
        elif not v[i] and s0 is not None:
            if (i - s0) * HOP / SR >= 0.05:
                runs.append((s0, i))
            s0 = None
    if s0 is not None:
        runs.append((s0, len(v)))
    merged = []
    for p, q in runs:
        q = min(q, len(tt) - 1)
        if merged and (p - merged[-1][1]) * HOP / SR < 0.06:
            merged[-1] = (merged[-1][0], q)
        else:
            merged.append((p, q))
    return merged, base, thr


def syllable_bounds(e, f0m, tt, p, q, min_syl=0.085):
    """发声段内按能量谷切音节。返回边界时刻列表。"""
    seg_e = e[p:q]
    cands = []
    for i in range(3, len(seg_e) - 3):
        w0 = seg_e[max(0, i - 4):i]
        w1 = seg_e[i:min(len(seg_e), i + 5)]
        if len(w0) < 2 or len(w1) < 2:
            continue
        lo_v = min(w0.mean(), w1.mean())
        win = seg_e[max(0, i - 6):i + 7]
        hi_v = float(win.max()) if len(win) else 1e-6
        if hi_v - lo_v > 0.28 * hi_v:
            cands.append(i)
    mc = []
    for i in cands:
        if mc and (i - mc[-1]) * HOP / SR < 0.07:
            continue
        mc.append(i)
    bounds = [p] + [p + i for i in mc] + [q]
    keep = [bounds[0]]
    for b in bounds[1:-1]:
        if (b - keep[-1]) * HOP / SR >= min_syl:
            keep.append(b)
    if keep[-1] != bounds[-1]:
        keep.append(bounds[-1])
    return [float(tt[b]) for b in keep]


# ---------------------------------------------------------------- 官方 TTML
TS_RE = None


def _ts(s):
    import re
    global TS_RE
    if TS_RE is None:
        TS_RE = re.compile(r"(\d+):(\d+(?:\.\d+)?)")
    m = TS_RE.search(s)
    if not m:
        return 0.0
    return float(m.group(1)) * 60 + float(m.group(2))


def parse_ttml(path):
    import re
    t = io.open(path, encoding="utf-8").read()
    body = t.split("<body", 1)[1]
    out = []
    for pm in re.finditer(r'<p\b([^>]*)>(.*?)</p>', body, re.S):
        chars = []
        for sm in re.finditer(r'<span\b([^>]*)>(.*?)</span>', pm.group(2), re.S):
            sa = sm.group(1)
            sb = re.search(r'\bbegin="([^"]+)"', sa)
            if not sb:
                continue
            txt = re.sub(r"<[^>]+>", "", sm.group(2))
            for ch in txt:
                if ch.strip():
                    chars.append((ch, _ts(sb.group(1))))
        if chars:
            out.append(chars)
    return out


def official_phrases(path):
    """返回 [(整句文本, [逐字时间])]"""
    res = []
    for chars in parse_ttml(path):
        res.append(("".join(c[0] for c in chars), [c[1] for c in chars]))
    return res


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default="separated/htdemucs/song/vocals.wav")
    ap.add_argument("--lines", default="out/lines_anchor.json")
    ap.add_argument("--ttml", default="work/qrc/song.ttml")
    ap.add_argument("--out", default="out/lines_mid.json")
    ap.add_argument("--lo", type=float, default=74.0)
    ap.add_argument("--hi", type=float, default=99.0)
    a = ap.parse_args()

    lines = json.load(io.open(a.lines, encoding="utf-8"))
    target = [l for l in lines if a.lo <= l["start"] <= a.hi]

    # --- 官方 TTML：找与本地句文字匹配的官方句
    off = official_phrases(a.ttml)
    joined_off = "".join(t for t, _ in off)
    print("官方 TTML：%d 句 / %d 字；本地目标区 %d 句"
          % (len(off), len(joined_off), len(target)))

    # 官方句 -> 本地句 的映射（按整句文字匹配，优先完全一致）
    used = set()
    mapping = {}
    for ln in target:
        txt = ln["text"]
        hit = None
        for i, (ot, ots) in enumerate(off):
            if i in used:
                continue
            if ot == txt:
                hit = (i, ot, ots)
                break
        if hit is None:
            # 允许官方句包含本地句（官方把多句并成一句）
            for i, (ot, ots) in enumerate(off):
                if i in used:
                    continue
                if txt in ot:
                    k = ot.index(txt)
                    hit = (i, ot, ots[k:k + len(txt)])
                    break
        if hit is not None:
            used.add(hit[0])
            mapping[id(ln)] = hit[2]
            print("  本地【%s】 → 官方【%s】(句%d) 官方首字 %.3f 末字 %.3f"
                  % (txt, hit[1], hit[0], hit[2][0], hit[2][-1]))
        else:
            print("  本地【%s】 → 官方无对应" % txt)

    # --- 我们自己人声轨的真实音节边界
    x, t = load_audio(a.audio, a.lo, a.hi)
    e, f0, tt = features(x)
    en = sm(e, 9)
    f0m = clean_f0(f0)
    f0m = np.where(f0m > 0, sm(f0m, 5), 0.0)
    segs, base, thr = voiced_segments(en, tt)
    print("\n人声轨发声段（%.2f–%.2f）:" % (a.lo, a.hi))
    bounds_all = []
    for p, q in segs:
        s0, s1 = a.lo + tt[p], a.lo + tt[q]
        print("   %7.3f → %7.3f (%.3fs)" % (s0, s1, s1 - s0))
        bs = syllable_bounds(en, f0m, tt, p, q)
        bounds_all.append((s0, s1, bs))

    # --- 逐句重排
    print("\n" + "=" * 78)
    out = []
    for ln in lines:
        if not (a.lo <= ln["start"] <= a.hi):
            out.append(ln)
            continue
        txt = ln["text"]
        n = len(txt)
        ots = mapping.get(id(ln))
        # 该句覆盖的所有音节边界
        syl = []
        for s0, s1, bs in bounds_all:
            for b in bs:
                if s0 - 0.02 <= b <= s1 + 0.02:
                    syl.append(b)
        syl = sorted(set(round(v, 3) for v in syl))
        # 只取句内（留一点余量）
        inside = [b for b in syl if ln["start"] - 0.55 <= b <= ln["end"] + 0.55]

        print("\n【%s】 %.2f → %.2f   (%d字)" % (txt, ln["start"], ln["end"], n))
        print("   音节边界: " + " ".join("%.2f" % v for v in inside))
        if ots:
            print("   官方相对: " + " ".join("%.2f" % (v - ots[0]) for v in ots))
        print("   当前     : " + " ".join("%.2f" % v for v in ln["times"]))

        if len(inside) < n:
            print("   ⚠ 音节数 %d < 字数 %d，本句不做自动重排" % (len(inside), n))
            out.append(ln)
            continue

        # 首字钉第一音节、尾字钉最后一音节，中间按累积实唱时长分配
        first, last = inside[0], inside[-1]
        seg_e = en
        mid_pool = inside[1:-1]

        # 累积实唱时长（跳过静音）
        cum, ctt = None, None
        i0 = int(np.searchsorted(tt, first - a.lo))
        i1 = int(np.searchsorted(tt, last - a.lo))
        if i1 > i0:
            vm = en[i0:i1] > thr
            cum = np.cumsum(vm).astype(float) * (HOP / SR)
            ctt = tt[i0:i1]

        if n == 1:
            times = [first]
        elif n == 2:
            times = [first, last]
        else:
            mid = np.empty(n - 2)
            if cum is not None and cum[-1] > 0.2:
                tot = cum[-1]
                for k in range(n - 2):
                    target_t = (k + 1) / (n - 1) * tot
                    j = int(np.searchsorted(cum, target_t))
                    mid[k] = float(ctt[min(j, len(ctt) - 1)]) + a.lo
            else:
                mid = np.linspace(first, last, n)[1:-1]
            # 吸附到真实音节边界（单调，一一对应）
            times = [first]
            pool = list(mid_pool)
            used = set()
            for m in mid:
                if not pool:
                    times.append(float(m))
                    continue
                # 找最近的未用边界
                order = sorted(range(len(pool)), key=lambda i: abs(pool[i] - m))
                pick = None
                for i in order:
                    if i not in used:
                        pick = i
                        break
                if pick is None:
                    times.append(float(m))
                else:
                    used.add(pick)
                    times.append(pool[pick])
            times.append(last)
            times = np.maximum.accumulate(np.array(times))
            avg = (last - first) / max(1, n - 1)
            floor_gap = max(0.075, 0.45 * avg)
            times[-1] = last
            for k in range(n - 2, -1, -1):
                times[k] = min(times[k], times[k + 1] - floor_gap)
            times[0] = first
            for k in range(1, n):
                if times[k] < times[k - 1] + 0.075:
                    times[k] = times[k - 1] + 0.075
            times[-1] = last

        print("   重排后   : " + " ".join("%.2f" % v for v in times))
        # 与官方相对节奏的相关性
        if ots and len(ots) == n:
            orel = np.array(ots) - ots[0]
            nrel = np.array(times) - times[0]
            cc = float(np.corrcoef(orel, nrel)[0, 1])
            print("   官方节奏相关 %.3f" % cc)
        out.append({**ln, "times": [round(float(v), 3) for v in times],
                    "fit": "syllable"})

    json.dump(out, io.open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n写入", a.out)


if __name__ == "__main__":
    main()
