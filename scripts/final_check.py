#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最终验收：抽帧目视 + 音轨对齐核对。

两件事：
  ① 抽目标区间的关键帧出来，确认字幕落在画面上、没有错位
  ② 把「字幕每字的点亮时刻」与「音轨上的真实音节」做最终核对，
     输出一份可交付的对齐表

## 判定口径

- 首字必须落在人声发声段内，且到最近强起音 ≤0.30s
- 尾字允许无起音（拖腔尾音），只要求落在发声段内，到起音 ≤0.45s

## 用法

```bash
python final_check.py --video out/final.mp4 --lines out/lines_sub.json \
    --audio separated/htdemucs/song/vocals.wav --lo 78 --hi 100
```
"""
import argparse
import io
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from realign_ttml import Track  # noqa


def grab(video, t, out):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t,
                    "-i", video, "-frames:v", "1", out], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="out/final.mp4")
    ap.add_argument("--lines", default="out/lines_sub.json")
    ap.add_argument("--audio", default="separated/htdemucs/song/vocals.wav")
    ap.add_argument("--outdir", default="work/check")
    ap.add_argument("--lo", type=float, default=78.0)
    ap.add_argument("--hi", type=float, default=100.0)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    lines = json.load(io.open(a.lines, encoding="utf-8"))
    tr = Track(a.audio)

    # 目标区间内的句子
    tgt = []
    for i, r in enumerate(lines):
        nz = [k for k, c in enumerate(r["text"]) if c.strip()]
        ts = [r["times"][k] for k in nz]
        if ts[-1] >= a.lo and ts[0] <= a.hi:
            tgt.append((i, r, nz, ts))

    print("目标区间 %s–%ss 命中 %d 句\n" % (a.lo, a.hi, len(tgt)))

    print("%-3s %-17s %-9s %-9s %-9s %-9s %s"
          % ("句", "文本", "首字", "首字起音", "尾字", "尾字起音", "判定"))
    ok = bad = 0
    for i, r, nz, ts in tgt:
        h = tr.nearest_onset(ts[0], 0.35)
        t = tr.nearest_onset(ts[-1], 0.35)
        hd = abs(h - ts[0]) if h else None
        td = abs(t - ts[-1]) if t else None
        # 判定：首字必须落在发声段内；尾字允许无起音（拖腔）
        v1 = tr.in_voiced(ts[0], 0.05)
        v2 = tr.in_voiced(ts[-1], 0.05)
        good = v1 and v2 and (hd is None or hd <= 0.30) and (td is None or td <= 0.45)
        ok += good
        bad += (not good)
        print("%-3d %-17s %9.3f %9s %9.3f %9s  %s"
              % (i, r["text"][:15], ts[0],
                 "%.3f" % h if h else "-", ts[-1],
                 "%.3f" % t if t else "-",
                 "✅" if good else "❌ 发声内 %s/%s" % (v1, v2)))
    print("\n通过 %d / %d 句" % (ok, ok + bad))

    # 抽帧
    print("\n抽帧（目标区间每句首字时刻 +0.15s）…")
    shots = []
    for i, r, nz, ts in tgt:
        for label, tt in (("head", ts[0] + 0.15), ("tail", ts[-1] + 0.15)):
            p = "%s/L%02d_%s.jpg" % (a.outdir, i, label)
            grab(a.video, tt, p)
            shots.append(p)
    print("已抽 %d 帧 → %s" % (len(shots), a.outdir))
    json.dump(shots, io.open(a.outdir + "/list.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
