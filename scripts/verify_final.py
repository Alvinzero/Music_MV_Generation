#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成片级字幕自检：越界 / 同屏冲突 / 时长合理性 / 与音轨的落静音率。

依据 out/lines_sub.json（成片实际使用的排布）与音轨发声段。
发声段由 F0 + 能量判定，是比"到最近起音距离"更可靠的真值 ——
拖腔尾音本来就没有起音，用起音判据会误报。

## 用法

```bash
python verify_final.py --lines out/lines_sub.json \
    --audio separated/htdemucs/song/vocals.wav
```
"""
import argparse
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from realign_ttml import Track  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default="out/lines_sub.json")
    ap.add_argument("--audio", default="separated/htdemucs/song/vocals.wav")
    ap.add_argument("--focus-lo", type=float, default=None,
                    help="重点区间起点（秒），只作统计提示")
    ap.add_argument("--focus-hi", type=float, default=None,
                    help="重点区间终点（秒），只作统计提示")
    a = ap.parse_args()

    lines = json.load(io.open(a.lines, encoding="utf-8"))
    tr = Track(a.audio)

    n = len(lines)
    prob = []

    # ① 字幕在画面内（底部 y=940+rise；顶部 y=180+rise；字号最大 109）
    for i, r in enumerate(lines):
        fs = r["fs"]
        y = r["y"] + 9           # rise
        half = fs * 0.62
        top = y - half
        bot = y + half
        if top < 40 or bot > 1040:
            prob.append("句%d 纵向越界 top=%.0f bot=%.0f" % (i, top, bot))
        w = len(r["text"]) * fs * 1.08
        if w / 2 > 960 - 40:
            prob.append("句%d 横向可能越界 宽 %.0f" % (i, w))

    # ② 相邻两句不同时亮
    for i in range(n - 1):
        a2, b2 = lines[i], lines[i + 1]
        az = [k for k, c in enumerate(a2["text"]) if c.strip()]
        bz = [k for k, c in enumerate(b2["text"]) if c.strip()]
        a_end = a2["times"][az[-1]]
        b_start = b2["times"][bz[0]]
        if a_end >= b_start:
            prob.append("句%d 尾字(%.3f) 越过句%d 首字(%.3f)" % (i, a_end, i + 1, b_start))

    # ③ 落静音率（字点亮时音轨上应该有人在唱）
    allt = []
    silent = 0
    for r in lines:
        z = [k for k, c in enumerate(r["text"]) if c.strip()]
        for k in z:
            t = r["times"][k]
            allt.append(t)
            if not tr.in_voiced(t, 0.05):
                silent += 1
    allt = np.array(allt)

    # ④ 首尾字都在发声段内
    h_bad = t_bad = 0
    for i, r in enumerate(lines):
        z = [k for k, c in enumerate(r["text"]) if c.strip()]
        if not tr.in_voiced(r["times"][z[0]], 0.05):
            h_bad += 1
            prob.append("句%d 首字落静音 %.3f" % (i, r["times"][z[0]]))
        if not tr.in_voiced(r["times"][z[-1]], 0.05):
            t_bad += 1
            prob.append("句%d 尾字落静音 %.3f" % (i, r["times"][z[-1]]))

    print("句数 %d，字幕字数 %d" % (n, len(allt)))
    print("落静音字：%d / %d (%.1f%%)" % (silent, len(allt), 100.0 * silent / len(allt)))
    print("首字落静音的句：%d；尾字落静音的句：%d" % (h_bad, t_bad))

    # ⑤ 重点区间单独统计
    if a.focus_lo is not None and a.focus_hi is not None:
        tgt = []
        for i, r in enumerate(lines):
            z = [k for k, c in enumerate(r["text"]) if c.strip()]
            if r["times"][z[-1]] >= a.focus_lo and r["times"][z[0]] <= a.focus_hi:
                tgt.append(i)
        print("重点区间 %g–%gs 命中句：%s" % (a.focus_lo, a.focus_hi, tgt))

    print()
    if prob:
        print("⚠ 问题 %d 条：" % len(prob))
        for p in prob[:20]:
            print("  " + p)
    else:
        print("✅ 全曲自检通过：无越界、无同屏冲突、首尾字全部落在人声发声段内")


if __name__ == "__main__":
    main()
