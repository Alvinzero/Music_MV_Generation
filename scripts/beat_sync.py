#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析歌曲速度与拍点，输出 beats.json。

流程：ffmpeg 解码 → 频谱通量 onset 包络 → 自相关估 BPM(60-180)
      → 网格搜索最佳相位 → 输出 bpm / beat_period / offset / beats[] / subdiv

用法:
    python beat_sync.py song.mp3 -o out/beats.json
"""

import argparse
import json
import subprocess
import sys

import numpy as np

SR = 22050
HOP = 512
NFFT = 2048


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def load_mono(path):
    cmd = [ffmpeg_exe(), "-v", "error", "-i", path,
           "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def onset_envelope(y):
    n = 1 + (len(y) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = y[idx] * np.hanning(NFFT)[None, :]
    spec = np.abs(np.fft.rfft(frames, axis=1))
    logspec = np.log1p(spec * 10.0)
    flux = np.diff(logspec, axis=0)
    flux[flux < 0] = 0.0
    env = flux.sum(axis=1)
    env -= env.mean()
    env = np.maximum(env, 0)
    if env.max() > 0:
        env /= env.max()
    return env


def estimate_bpm(env, fps):
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac[:1] = 0
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)
    hi = min(hi, len(ac) - 1)
    if hi <= lo:
        return 90.0
    lag = lo + int(np.argmax(ac[lo:hi]))
    if 0 < lag < len(ac) - 1:
        y0, y1, y2 = ac[lag - 1], ac[lag], ac[lag + 1]
        denom = (y0 - 2 * y1 + y2)
        if denom != 0:
            lag = lag + 0.5 * (y0 - y2) / denom
    return 60.0 * fps / lag


def best_phase(env, fps, bpm):
    period = 60.0 / bpm * fps
    best, best_off = -1e18, 0.0
    for off in np.arange(0, period, 0.5):
        pos = np.arange(off, len(env), period)
        i = np.floor(pos).astype(int)
        i = i[i < len(env)]
        if len(i) < 8:
            continue
        score = env[i].sum() / len(i) ** 0.5
        if score > best:
            best, best_off = score, off
    return best_off


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("-o", "--out", default="beats.json")
    a = ap.parse_args()

    y = load_mono(a.audio)
    fps = SR / HOP
    env = onset_envelope(y)
    bpm = estimate_bpm(env, fps)
    off = best_phase(env, fps, bpm)
    beat0 = off / fps
    period = 60.0 / bpm
    grid, t = [], beat0
    while t < len(y) / SR + period:
        if t >= 0:
            grid.append(round(t, 4))
        t += period
    data = {
        "bpm": round(bpm, 2),
        "beat_period": round(period, 4),
        "offset": round(beat0, 4),
        "duration": round(len(y) / SR, 3),
        "beats": grid,
        "subdiv": {"1": round(period, 4), "2": round(period / 2, 4),
                   "4": round(period / 4, 4), "8": round(period / 8, 4)},
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("BPM %.2f  相位 %.3fs  拍点 %d 个  时长 %.2fs"
          % (bpm, beat0, len(grid), data["duration"]))
    print("1/8 拍网格 %.4fs → 所有切点与字幕都对到这个网格" % (period / 8))


if __name__ == "__main__":
    main()
