#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按"拍点对齐"生成 xfade 时间线滤镜脚本。

做三件事：
  1. 把内部切点吸附到最近的拍点（首尾不动）
  2. 叠化中点压拍：xfade 的 offset = 切点 − fade/2
  3. 对超出素材长度的镜头自动加 setpts + minterpolate 慢放

用法:
    python make_timeline.py --bounds 0,4.9,8.3,11.7,15.6,18.9 --beats beats.json \
        --total 56.026 --clip-len 6.04 --fade 0.5 --out filter_base.txt

注意：--bounds 必须包含首尾（第一个 0，最后一个等于 --total）。
渲染时按 bounds 顺序把 clips 依次作为 -i 输入即可。
"""

import argparse
import json

import numpy as np


def load_beats(path):
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    return b["beat_period"], b["offset"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounds", required=True, help="逗号分隔的切点，含首尾")
    ap.add_argument("--beats", required=True)
    ap.add_argument("--total", type=float, required=True)
    ap.add_argument("--clip-len", default="6.04",
                    help="单段素材实际时长：一个数字，或逗号分隔的每镜实测值（顺序与 bounds 一致）。"
                         "镜头时长现在是 4–15s 动态的，务必传每镜实测值")
    ap.add_argument("--fade", type=float, default=0.5)
    ap.add_argument("--no-snap", action="store_true", help="不吸附拍点")
    ap.add_argument("--fadeblack", default="", help="需要黑场过渡的转场序号，如 5,8")
    ap.add_argument("--out", default="filter_base.txt")
    a = ap.parse_args()

    raw = [float(x) for x in a.bounds.split(",")]
    if abs(raw[0]) > 1e-6 or abs(raw[-1] - a.total) > 0.01:
        raise SystemExit("--bounds 必须包含首尾：第一个 0，最后一个等于 --total")

    if a.no_snap:
        bounds = raw
    else:
        per, off = load_beats(a.beats)
        bounds = [raw[0]] + [round(off + round((b - off) / per) * per, 3)
                             for b in raw[1:-1]] + [raw[-1]]
        moved = [round(n - o, 3) for n, o in zip(bounds, raw)]
        print("吸附位移:", moved)

    N = len(bounds) - 1
    durs = [round(bounds[i + 1] - bounds[i], 3) for i in range(N)]
    durs[-1] = round(a.total - sum(durs[:-1]), 3)

    D = a.fade
    # 素材时长可能是 4–15s 里任意值，单个数字只对「全片同一时长」成立。
    lens = [float(x) for x in str(a.clip_len).split(",") if x.strip()]
    if len(lens) == 1:
        lens = lens * N
        if abs(lens[0] - 6.04) < 1e-9:
            print("提醒：--clip-len 用的是默认 6.04，动态时长下会算错慢放；"
                  "建议传每镜实测值（逗号分隔）")
    if len(lens) != N:
        raise SystemExit("--clip-len 给了 %d 个值，但镜头有 %d 个，数量必须一致" % (len(lens), N))

    slow = {}
    for i in range(N):
        need = (durs[i] + D) if i < N - 1 else durs[i]
        if need > lens[i]:
            slow[i + 1] = need / lens[i]

    fb = set(int(x) for x in a.fadeblack.split(",") if x.strip())
    lines = []
    for i in range(1, N + 1):
        need = (durs[i - 1] + D) if i < N else durs[i - 1]
        if i in slow:
            lines.append(
                f"[{i-1}:v]setpts={slow[i]:.4f}*PTS,minterpolate=fps=24:mi_mode=blend,"
                f"trim=duration={need:.3f},setpts=PTS-STARTPTS,fps=24,format=yuv420p,settb=AVTB[v{i}]")
        else:
            lines.append(
                f"[{i-1}:v]trim=duration={need:.3f},setpts=PTS-STARTPTS,fps=24,"
                f"format=yuv420p,settb=AVTB[v{i}]")

    prev, cum = "v1", 0.0
    for k in range(1, N):
        cum += durs[k - 1]
        out = "[out]" if k == N - 1 else f"[x{k}]"
        tr = "fadeblack" if k in fb else "fade"
        lines.append(f"[{prev}][v{k+1}]xfade=transition={tr}:duration={D}:offset={cum - D / 2:.3f}{out}")
        prev = out.strip("[]")

    with open(a.out, "w", encoding="utf-8") as f:
        f.write(";\n".join(lines))

    print("镜头数 %d  合计 %.3fs" % (N, sum(durs)))
    print("时长", durs)
    print("慢放:", {k: round(v, 3) for k, v in slow.items()} or "无（全部常速）")
    print("切点与拍点误差:")
    if not a.no_snap:
        for b in bounds[1:-1]:
            k = round((b - off) / per)
            print("   %.3fs  距拍点 %+.4fs" % (b, b - (off + k * per)))


if __name__ == "__main__":
    main()
