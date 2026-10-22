#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给已烧录的 ASS 逐字重定时（只改 Start，不动文本/位置/色彩）。

    python retime.py --ass out/subs.ass --audio song.m4a -o out/subs_v2.ass

思路：
  1. HPSS 去掉打击乐，只留谐波（人声）→ 250–4200Hz 谱通量，4ms 步长
  2. 局部归一化（1.5s 滑动中位），让前奏/副歌的峰可比
  3. 按 ASS 的 End 时间把逐字事件分组成「句」
  4. 每句：全局位移 δ 搜索 + 句内逐字 DP，代价含节奏先验与峰强
  5. 只替换 Start 字段，其余字节原样保留
"""
import argparse
import io
import re
import shutil
import subprocess
import sys

import numpy as np
from scipy.ndimage import median_filter

SR, NFFT, HOP = 16000, 512, 64
FPS = SR / HOP


def find_ffmpeg():
    for cand in (r"D:/workbuddy/runtime/ffmpeg/ffmpeg.exe",
                 shutil.which("ffmpeg"),
                 r"C:/Users/Admin/.workbuddy/binaries/ffmpeg/ffmpeg.exe"):
        if cand:
            import os
            if os.path.exists(cand):
                return cand
    sys.exit("找不到 ffmpeg")


FF = find_ffmpeg()


def onset_env(path):
    raw = subprocess.run([FF, "-v", "error", "-i", path, "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = 1 + (len(x) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(NFFT).astype(np.float32)[None, :], axis=1))

    # HPSS：时间方向中位 = 谐波（人声/乐器持续音），频率方向中位 = 打击
    harm = median_filter(spec, size=(1, 17), mode="nearest")
    freqs = np.fft.rfftfreq(NFFT, 1.0 / SR)
    band = (freqs > 250) & (freqs < 4200)
    h = np.log1p(harm[:, band] * 12.0)

    flux = np.maximum(0.0, np.diff(h, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    # 局部归一化：减去 1.5s 滑动中位数，压掉段落响度差
    k = int(1.5 * FPS) | 1
    base = median_filter(flux, size=k, mode="nearest")
    nov = np.maximum(0.0, flux - base)
    nov /= (np.percentile(nov, 99.5) + 1e-9)
    nov = np.convolve(nov, np.ones(3) / 3, mode="same")
    return nov, np.arange(n) * HOP / SR


def parse_ass(path):
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    evs = []
    for ln in lines:
        if not ln.startswith("Dialogue:"):
            continue
        parts = ln.split(",", 9)
        if len(parts) < 10:
            continue
        h, m, s = parts[1].split(":")
        eh, em, es = parts[2].split(":")
        text = parts[9]
        plain = re.sub(r"\{[^}]*\}", "", text)
        evs.append(dict(raw=ln, layer=parts[0], t0=float(h) * 3600 + float(m) * 60 + float(s),
                        t1=float(eh) * 3600 + float(em) * 60 + float(es),
                        style=parts[3], text=text, plain=plain))
    return lines, evs


def group_by_end(evs):
    groups = {}
    for i, e in enumerate(evs):
        groups.setdefault(round(e["t1"], 2), []).append(i)
    out = []
    for end in sorted(groups):
        idx = sorted(groups[end], key=lambda i: evs[i]["t0"])
        out.append((end, idx))
    return out


def fmt(t):
    t = max(0.0, t)
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60); t -= m * 60
    return "%d:%02d:%05.2f" % (h, m, t)


def peaks_in(nov, t, lo, hi, thr=0.10, sep=0.045):
    m = (t >= lo) & (t <= hi)
    if not m.any():
        return np.array([]), np.array([])
    tt, ff = t[m], nov[m]
    pt, pf, last = [], [], -9.0
    for i in range(1, len(ff) - 1):
        if ff[i] >= ff[i - 1] and ff[i] > ff[i + 1] and ff[i] > thr and tt[i] - last >= sep:
            pt.append(tt[i]); pf.append(ff[i]); last = tt[i]
    return np.array(pt), np.array(pf)


def dp_align(pt, expect, lam=0.9):
    N, M = len(expect), len(pt)
    if M < N:
        return None
    step = (expect[-1] - expect[0]) / max(1, N - 1) if N > 1 else 0.3
    INF = 1e9
    dp = np.full((N, M), INF)
    bk = np.zeros((N, M), dtype=int)
    dp[0] = np.abs(pt - expect[0])
    for k in range(1, N):
        for i in range(k, M):
            trans = dp[k - 1, :i] + lam * np.abs((pt[i] - pt[:i]) - step)
            j = int(np.argmin(trans))
            dp[k, i] = trans[j] + abs(pt[i] - expect[k])
            bk[k, i] = j
    i = int(np.argmin(dp[N - 1]))
    pick = [i]
    for k in range(N - 1, 0, -1):
        i = int(bk[k, i]); pick.append(i)
    return pt[sorted(set(pick))]


def novelty_at(nov, t, times, tol=0.045):
    v = []
    for x in times:
        m = (t >= x - tol) & (t <= x + tol)
        v.append(nov[m].max() if m.any() else 0.0)
    return float(np.mean(v)) if v else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ass", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("-o", "--out", default="out/subs_v2.ass")
    ap.add_argument("--max-shift", dest="max_shift", type=float, default=0.60)
    a = ap.parse_args()

    nov, t = onset_env(a.audio)
    lines, evs = parse_ass(a.ass)
    groups = group_by_end(evs)
    print("事件 %d 个，分成 %d 句" % (len(evs), len(groups)))

    new_t0 = {}
    old_bt, new_bt = [], []
    moved = 0
    for end, idx in groups:
        chars = [evs[i]["plain"].strip() for i in idx]
        if not any(chars) or any(len(c) > 1 for c in chars):
            for i in idx:                      # 非逐字（整行/图形）不动
                new_t0[i] = evs[i]["t0"]
            continue
        old = np.array([evs[i]["t0"] for i in idx], float)
        order = np.argsort(old)
        idx = [idx[k] for k in order]
        old = old[order]
        n = len(idx)
        line_start = old[0]

        pt, pf = peaks_in(nov, t, line_start - 0.75, max(end, line_start + 0.6))
        if len(pf) > n + 10:
            keep = np.argsort(pf)[-(n + 10):]
            keep.sort()
            pt, pf = pt[keep], pf[keep]

        best = None
        for d in np.arange(-a.max_shift, a.max_shift + 1e-9, 0.02):
            expect = old + d
            if n == 1:
                sel = np.array([expect[0]])
                if len(pt):
                    j = int(np.argmin(np.abs(pt - expect[0])))
                    if abs(pt[j] - expect[0]) < 0.35:
                        sel = np.array([pt[j]])
            else:
                sel = dp_align(pt, expect)
                if sel is None or len(sel) != n:
                    continue
            sel = np.asarray(sel, float)
            gain = novelty_at(nov, t, sel)
            cost = -gain + 0.55 * float(np.abs(sel - expect).mean()) + 0.10 * abs(d)
            if best is None or cost < best[0]:
                best = (cost, sel, d)

        if best is None:
            for i, x in zip(idx, old):
                new_t0[i] = x
            old_bt.append(novelty_at(nov, t, old)); new_bt.append(novelty_at(nov, t, old))
            continue

        _, sel, d = best
        sel = np.clip(np.asarray(sel, float), old - 0.55, old + 0.55)   # 单字位移不超过半秒
        # 单调 + 最小间隔
        sel = list(sel)
        for k in range(1, n):
            if sel[k] < sel[k - 1] + 0.06:
                sel[k] = sel[k - 1] + 0.06
        if sel[-1] > end - 0.04:
            for k in range(n):
                sel[k] = min(sel[k], end - 0.05)
        for i, x in zip(idx, sel):
            new_t0[i] = x
        old_bt.append(novelty_at(nov, t, old))
        new_bt.append(novelty_at(nov, t, sel))
        if abs(d) > 0.02:
            moved += 1

    ob = np.array(old_bt); nb = np.array(new_bt)
    print("起音解释力（越高越好）：旧 %.3f → 新 %.3f  (+%.1f%%)"
          % (ob.mean(), nb.mean(), 100 * (nb.mean() / (ob.mean() + 1e-9) - 1)))
    print("整句位移的句子：%d / %d" % (moved, len(groups)))

    # 只改 Start
    out = []
    for ln in lines:
        if ln.startswith("Dialogue:"):
            parts = ln.split(",", 9)
            for i, e in enumerate(evs):
                if e["raw"] is ln:
                    parts[1] = fmt(new_t0[i])
                    break
            out.append(",".join(parts))
        else:
            out.append(ln)
    io.open(a.out, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("写入", a.out)


if __name__ == "__main__":
    main()
