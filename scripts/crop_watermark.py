#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键裁水印：先测 bbox，按 bbox 对称裁，再复测——三步一条命令。

    python scripts/crop_watermark.py --src raw.mp4 --out clips/s01.mp4
    python scripts/crop_watermark.py --src raw.mp4 --out crops/s01.mp4 --keep-height

为什么不能套固定 crop 值：水印位置随机器/版本变（实测 110px 和 240px 两种情况），
漏一点就留半截字。所以这里一律"先量后裁"。

裁完会自动再跑一次检测，不干净就返回 2。
"""
import argparse
import json
import shutil
import subprocess
import sys

import check_title as CT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pad", type=int, default=10, help="水印 bbox 外再留几像素")
    ap.add_argument("--scale-back", action="store_true", default=True,
                    help="裁完拉回原尺寸（默认开）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    info = CT.probe(a.src)
    W, H = info["w"], info["h"]
    if not W:
        sys.exit("读不到尺寸：%s" % a.src)

    dur = info["dur"] or 6.0
    frames = [CT.grab(a.src, dur * p) for p in (0.05, 0.5, 0.95)]
    frames = [f for f in frames if f is not None]
    if not frames:
        sys.exit("抽不到画面")

    # 找打分最高的那个角
    best = dict(score=0.0, bbox=None, corner=None)
    for name, box in CT.corners(frames[0]).items():
        for f in frames:
            s, b = CT.wm_score(f, box)
            if s > best["score"]:
                best = dict(score=s, bbox=b, corner=name, frame=f)

    if best["score"] < 0.35 or not best["bbox"]:
        print("四角未检出明显水印（最高分 %.2f），不做裁切。" % best["score"])
        if a.out:
            shutil.copyfile(a.src, a.out)
            print("已复制到", a.out)
        return

    x0, y0, x1, y1 = best["bbox"]
    pad = a.pad
    # 对称裁：左边裁多少，右边也裁多少，保持构图居中
    if best["corner"] in ("左上", "左下"):
        cut_l = min(x1 + pad, W // 4)
        cut_r = cut_l
    else:
        cut_r = min(W - x0 + pad, W // 4)
        cut_l = cut_r
    cut_t = min(y1 + pad, H // 6) if best["corner"] in ("左上", "右上") else 0
    cut_b = min(H - y0 + pad, H // 6) if best["corner"] in ("左下", "右下") else 0

    cw, ch = W - cut_l - cut_r, H - cut_t - cut_b
    if cw <= 100 or ch <= 100:
        sys.exit("裁切后尺寸异常 %dx%d，检查 --pad" % (cw, ch))

    vf = "crop=%d:%d:%d:%d" % (cw, ch, cut_l, cut_t)
    if a.scale_back:
        vf += ",scale=%d:%d:flags=lanczos" % (W, H)

    cmd = [CT.FF, "-y", "-v", "error", "-i", a.src, "-vf", vf,
           "-c:v", "libx264", "-preset", "slow", "-crf", "17",
           "-pix_fmt", "yuv420p", "-an", a.out]
    subprocess.run(cmd, check=True)

    rep = dict(corner=best["corner"], bbox=best["bbox"], score=best["score"],
               crop=dict(w=cw, h=ch, x=cut_l, y=cut_t), out=a.out)

    # 复测
    f2 = [CT.grab(a.out, dur * p) for p in (0.05, 0.5, 0.95)]
    f2 = [f for f in f2 if f is not None]
    worst = 0.0
    for name, box in CT.corners(f2[0]).items():
        for f in f2:
            s, _ = CT.wm_score(f, box)
            worst = max(worst, s)
    rep["after"] = round(worst, 3)
    rep["pass"] = worst < 0.35

    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("水印 %s角 %.2f @ %s" % (best["corner"], best["score"], best["bbox"]))
        print("裁切 crop=%d:%d:%d:%d（左右各 %d，上 %d）→ 复测最高分 %.2f"
              % (cw, ch, cut_l, cut_t, cut_l, cut_t, worst))
        print("写入 %s" % a.out)
        print("[通过]" if rep["pass"] else "[仍有残留] 调大 --pad 或换角重试")

    if not rep["pass"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
