#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对齐自检：把每句的预测起点和最近的人声起音峰比一比，看误差分布。

    python diag_sync.py --audio song.m4a --lines out/lines_aligned.json

判读：
  * 平均偏差≈0 但标准差大 → 逐句随机漂移（起点估得不准）
  * 平均偏差明显非 0 → 整体平移，做一次全局修正即可
  * |偏差| > 0.25s 的句子会被逐条列出，人工核对

健康的数：中位 |偏差| < 0.12s，最大 < 0.55s。
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
    return np.convolve(flux, np.ones(5) / 5, mode="same"), np.arange(frames) * HOP / SR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--lines", required=True)
    ap.add_argument("--window", type=float, default=0.75)
    a = ap.parse_args()

    flux, t = onset_curve(a.audio)
    lines = json.load(open(a.lines, encoding="utf-8"))

    print("%4s %9s %10s %8s" % ("#", "预测起点", "最近人声峰", "位移"))
    off = []
    for it in lines:
        t0 = float(it["start"])
        m = (t >= t0 - a.window) & (t <= t0 + a.window)
        if not m.any():
            continue
        seg_t, seg_f = t[m], flux[m]
        j = int(np.argmax(seg_f))
        dt = seg_t[j] - t0
        off.append(dt)
        flag = "" if abs(dt) < 0.18 else ("  <-- 偏大" if seg_f[j] > 0.05 else "")
        print("%4d %9.2f %10.2f %+8.2f  (%.3f)%s"
              % (it.get("n", 0), t0, seg_t[j], dt, seg_f[j], flag))

    if not off:
        sys.exit("没有可比对的句子")
    off = np.array(off)
    print("\n平均 %+.3fs  中位 %+.3fs  标准差 %.3fs  最大 %.2fs"
          % (off.mean(), np.median(off), off.std(), np.abs(off).max()))
    print("|偏差| > 0.25s 的句子: %d / %d" % (int((np.abs(off) > 0.25).sum()), len(off)))


if __name__ == "__main__":
    main()
