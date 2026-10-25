#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析歌曲结构（主歌/副歌/桥段），并给出分镜数量与成本估算。

长片（2 分钟以上）不能平均铺镜头——副歌该切得密、主歌该留得住。
本脚本用「相邻窗特征差异」找段落边界，再用响度区分副歌与主歌。

用法:
    python song_structure.py --audio song.mp3 -o out/structure.json
    python song_structure.py --audio song.mp3 --shots          # 只输出分镜建议
"""

import argparse
import json
import subprocess

import numpy as np

SR = 22050
HOP = 512
NFFT = 2048

# 每种段落建议的单镜时长（秒）——副歌快、主歌慢、前奏尾奏更长
SHOT_LEN = {"intro": 6.0, "verse": 5.0, "chorus": 3.2, "bridge": 4.0, "outro": 6.0}
COST_PER_SHOT = 93          # 单镜成本 ≈ 一张图 8 + 一段 6s 视频 85（credits）


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


def features(y):
    n = 1 + (len(y) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = y[idx] * np.hanning(NFFT)[None, :]
    spec = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)

    # 24 个对数频带
    edges = np.geomspace(80, 8000, 25)
    bands = np.zeros((spec.shape[0], 24), dtype=np.float32)
    for i in range(24):
        m = (freqs >= edges[i]) & (freqs < edges[i + 1])
        if m.any():
            bands[:, i] = spec[:, m].mean(axis=1)
    bands = np.log1p(bands * 20)

    # 逐帧能量
    rms = np.sqrt((frames ** 2).mean(axis=1))
    fps = SR / HOP
    return bands, rms, fps


def novelty(bands, win_sec=2.0, fps=43.0):
    """相邻窗均值差 → 段落边界处的局部峰值。"""
    W = max(4, int(win_sec * fps))
    T, D = bands.shape
    cs = np.cumsum(np.vstack([np.zeros(D), bands]), axis=0)   # (T+1, D)

    def mean(a, b):
        a, b = max(0, a), min(T, b)
        if b <= a:
            return np.zeros(D)
        return (cs[b] - cs[a]) / (b - a)

    nov = np.zeros(T)
    for t in range(T):
        left = mean(t - W, t)
        right = mean(t, t + W)
        nov[t] = np.linalg.norm(right - left)
    nov = nov / (nov.max() + 1e-9)
    return nov


def pick_boundaries(nov, fps, min_gap=8.0, thr=0.18):
    gap = int(min_gap * fps)
    cand = []
    for i in range(1, len(nov) - 1):
        if nov[i] > thr and nov[i] >= nov[i - 1] and nov[i] >= nov[i + 1]:
            if not cand or i - cand[-1] >= gap:
                cand.append(i)
            elif nov[i] > nov[cand[-1]]:
                cand[-1] = i
    return cand


def label_sections(bounds, rms, fps):
    """按段内响度相对中位数分主歌/副歌。"""
    levels = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        levels.append(float(np.mean(rms[int(a * fps):int(b * fps)])) if b > a else 0.0)
    med = float(np.median(levels)) if levels else 1.0
    out = []
    for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        if i == 0 and b - a < 18:
            lab = "intro"
        elif i == len(bounds) - 2 and b - a < 18:
            lab = "outro"
        else:
            lab = "chorus" if levels[i] > med * 1.06 else "verse"
        out.append(dict(start=round(a, 2), end=round(b, 2), dur=round(b - a, 2),
                        label=lab, level=round(levels[i] / (med + 1e-9), 2)))
    return out


def douyin_checkpoints(secs, dur):
    """只按音频结构给出留存检查点，不代替剧情判断。

    包含首帧 0s、3s、段落边界和每 25s 检查点，供双轨分镜安排有效变化。
    """
    marks = {0.0, 3.0}
    for s in secs:
        if s["label"] == "intro" and s["end"] < dur:
            marks.add(float(s["end"]))
        else:
            marks.add(float(s["start"]))
    t = 25.0
    while t < dur:
        marks.add(t)
        t += 25.0
    return [round(x, 2) for x in sorted(marks) if x <= dur]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("-o", "--out", default="")
    ap.add_argument("--shots", action="store_true", help="只打印分镜建议")
    a = ap.parse_args()

    y = load_mono(a.audio)
    bands, rms, fps = features(y)
    nov = novelty(bands, 2.0, fps)
    dur = len(y) / SR

    min_seg = 6.0
    if dur < 90:
        # 一分钟左右的短片没有分段意义，按一整段处理
        secs = [dict(start=0.0, end=round(dur, 2), dur=round(dur, 2),
                     label="verse", level=1.0)]
    else:
        cuts = pick_boundaries(nov, fps)
        bs = [0.0]
        for c in cuts:
            t = c / fps
            if t - bs[-1] < min_seg:
                if len(bs) > 1:
                    bs[-1] = t
            else:
                bs.append(t)
        bs.append(dur)
        if len(bs) > 2 and bs[-1] - bs[-2] < min_seg:
            bs.pop(-2)
        secs = label_sections(bs, rms, fps)

    total_shots, plan = 0, []
    for s in secs:
        ln = SHOT_LEN.get(s["label"], 4.5)
        cnt = max(1, int(round(s["dur"] / ln)))
        s["shot_len"] = ln
        s["shots"] = cnt
        total_shots += cnt
        plan.append(s)

    if not a.shots:
        print("时长 %.1fs（%.1f 分钟），检测到 %d 个段落" % (dur, dur / 60, len(secs)))
        print("-" * 58)
        for s in plan:
            print("  %6.1f–%6.1f  %-7s  强度 %.2f  → 单镜 %.1fs × %2d 个"
                  % (s["start"], s["end"], s["label"], s["level"], s["shot_len"], s["shots"]))
    print("-" * 58)
    print("分镜合计 %d 个，预估成本 ≈ %d credits（按 %d/镜）"
          % (total_shots, total_shots * COST_PER_SHOT, COST_PER_SHOT))

    if a.out:
        douyin = {
            "hook_window_sec": [0.0, 3.0],
            "change_checkpoints_sec": douyin_checkpoints(plan, dur),
            "max_change_gap_sec": 25.0,
            "note": "检查点只来自音频结构；每点放什么推流任务由双轨分镜决定",
        }
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(dict(duration=round(dur, 2), sections=plan,
                           total_shots=total_shots,
                           est_credits=total_shots * COST_PER_SHOT,
                           douyin=douyin),
                      f, ensure_ascii=False, indent=1)
        print("已写入:", a.out)


if __name__ == "__main__":
    main()
