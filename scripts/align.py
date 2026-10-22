#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚠️ 已由 align_subs.py 取代（2026-10-22）。

本项目统一到一套算法：HPSS 去鼓 + 250–4200Hz + 4ms + 局部归一（见 align_core.py）。
本文件仍保留，是因为它的 250–3200Hz/10ms 前端可作对照实验，**不要在新流程里调用**。

把歌词文本对齐到实际人声（起音对齐，不依赖声学模型）。

    python align.py --audio song.m4a --lines out/lyrics.json -o out/lines_aligned.json

输入 lines.json：[{"n":1,"start":10.65,"end":15.06,"text":"这风铃 跟心动很接近"}, ...]
输出：原字段 + times（每个字的绝对时刻）+ fit（dp/uniform）+ shift（整句位移）

四步：
  1. 250–3200Hz 谱通量取峰（人声主区，避开低频鼓）
  2. 每句在 ±0.55s 内搜索最优整体位移（整句联合，不是单峰吸附）
  3. 句内逐字 DP，转移代价含「间隔偏离惩罚」，防止拉出长空洞
  4. 安全阀：任意两字间隔收在 0.45–1.85 倍步长

⚠️ 有 Demucs 分出的人声轨就一定要传人声轨（--audio vocals.wav）。
直接在混音上跑会被军鼓带偏：实测句起点标准差 0.415s，59 句里 38 句偏 >0.25s。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import numpy as np

SR, HOP, NFFT = 16000, 160, 1024


def find_ffmpeg():
    for cand in (r"D:/workbuddy/runtime/ffmpeg/ffmpeg.exe",
                 shutil.which("ffmpeg"),
                 r"C:/Users/Admin/.workbuddy/binaries/ffmpeg/ffmpeg.exe",
                 r"C:/Users/Admin/.local/bin/ffmpeg.exe"):
        if cand and os.path.exists(cand):
            return cand
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("找不到 ffmpeg")


FF = find_ffmpeg()


def onset_curve(path):
    raw = subprocess.run([FF, "-v", "error", "-i", path, "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True).stdout
    if not raw:
        sys.exit("解码失败: %s" % path)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    frames = 1 + (len(x) - NFFT) // HOP
    win = np.hanning(NFFT).astype(np.float32)
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * win, axis=1))
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    s = spec[:, (freqs > 250) & (freqs < 3200)]
    flux = np.maximum(0, np.diff(s, axis=0)).sum(axis=1)
    flux = np.concatenate([[0], flux])
    flux = flux / (flux.max() + 1e-9)
    flux = np.convolve(flux, np.ones(5) / 5, mode="same")
    return flux, np.arange(frames) * HOP / SR


def peaks(flux, t, lo, hi, thr=0.075, sep=0.10):
    m = (t >= lo) & (t <= hi)
    if not m.any():
        return np.array([]), np.array([])
    tt, ff = t[m], flux[m]
    out_t, out_f, last = [], [], -9.0
    for i in range(1, len(ff) - 1):
        if ff[i] >= ff[i - 1] and ff[i] > ff[i + 1] and ff[i] > thr:
            if tt[i] - last >= sep:
                out_t.append(tt[i])
                out_f.append(ff[i])
                last = tt[i]
    return np.array(out_t), np.array(out_f)


def dp_align(pt, expect, lam=0.75):
    """按顺序挑 len(expect) 个峰；代价含间隔偏离惩罚，防止长空洞。"""
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
        i = int(bk[k, i])
        pick.append(i)
    return pt[sorted(set(pick))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="整曲，或 Demucs 分离出的人声轨")
    ap.add_argument("--lines", required=True)
    ap.add_argument("-o", "--out", default="out/lines_aligned.json")
    ap.add_argument("--max-shift", dest="max_shift", type=float, default=0.55)
    ap.add_argument("--no-shift", dest="no_shift", action="store_true")
    a = ap.parse_args()

    flux, tt = onset_curve(a.audio)
    lyrics = json.load(open(a.lines, encoding="utf-8"))
    base_starts = [float(it["start"]) for it in lyrics]
    out = []

    for i, it in enumerate(lyrics):
        base = base_starts[i]
        e0 = max(float(it["end"]), base + 0.9)
        if i + 1 < len(lyrics):
            e0 = min(e0, base_starts[i + 1] - 0.42)   # 给下一句留清场时间
        chars = "".join(c for c in it["text"] if c.strip())
        n = len(chars)

        pt, pf = peaks(flux, tt, base - 0.70, e0 - 0.05)
        if len(pf) > n + 8:
            keep = np.argsort(pf)[-(n + 8):]
            keep.sort()
            pt, pf = pt[keep], pf[keep]

        best = None
        shifts = [0.0] if a.no_shift else np.arange(-a.max_shift, a.max_shift + 1e-9, 0.02)
        for d in shifts:
            s = base + d
            e = max(e0 + d, s + 0.9)
            if e - s < 0.6:
                continue
            expect = s + (np.arange(n) + 0.35) * (e - s) / n
            sel = dp_align(pt, expect)
            if sel is None or len(sel) != n:
                continue
            f_sel = np.interp(sel, pt, pf) if len(pt) else np.zeros(n)
            cost = (float(np.abs(sel - expect).mean())
                    - 0.30 * float(f_sel.mean()) + 0.06 * abs(d))
            if best is None or cost < best[0]:
                best = (cost, d, sel, s, e)

        if best is None:
            s, e, d = base, e0, 0.0
            times = list(s + np.arange(n) * (e - s) / n)
            fit = "uniform"
        else:
            _, d, sel, s, e = best
            times = list(np.clip(sel, s, e - 0.15))
            times[0] = s
            step = (e - s) / n
            for k in range(1, n):             # 安全阀
                lo_t = times[k - 1] + max(0.07, 0.45 * step)
                hi_t = times[k - 1] + 1.85 * step
                times[k] = min(max(times[k], lo_t), max(hi_t, lo_t))
            if times[-1] > e - 0.12:
                times = [s + j * (e - s - 0.12) / n for j in range(n)]
            fit = "dp"

        out.append(dict(n=it.get("n", i + 1), start=round(s, 2), end=round(e, 2),
                        text=it["text"], times=[round(v, 2) for v in times],
                        fit=fit, shift=round(d, 2)))

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    sh = np.array([o["shift"] for o in out])
    dpn = sum(1 for o in out if o["fit"] == "dp")
    bad = []
    for o in out:
        d = np.diff(o["times"])
        if len(d) and (d.max() > 1.25 or d.min() < 0.06):
            bad.append(o["n"])
    print("句数 %d   DP 逐字对齐 %d / 均分兜底 %d" % (len(out), dpn, len(out) - dpn))
    print("整体位移：平均 %+.3fs  中位 |%.3f|  最大 |%.2f|"
          % (sh.mean(), np.median(np.abs(sh)), np.abs(sh).max()))
    print("异常间隔的句子:", bad if bad else "无")
    print("写入", a.out)


if __name__ == "__main__":
    main()
