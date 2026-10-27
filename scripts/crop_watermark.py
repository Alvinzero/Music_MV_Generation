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

from PIL import Image

import check_title as CT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pad", type=int, default=10, help="水印 bbox 外再留几像素")
    ap.add_argument("--scale-back", action="store_true", default=True,
                    help="裁完拉回原尺寸（默认开）")
    ap.add_argument("--size", default="", help="输出尺寸 WxH，如 1920x1080；不给就拉回原尺寸")
    ap.add_argument("--right", type=int, default=0, help="直接裁掉右侧 N 像素（跳过检测，批量用）")
    ap.add_argument("--bottom", type=int, default=0, help="直接裁掉底部 N 像素（跳过检测，批量用）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    info = CT.probe(a.src)
    W, H = info["w"], info["h"]
    still = info["dur"] <= 0          # 静帧没有时长，grab 抽不到，直接读图
    if still:
        base = Image.open(a.src).convert("RGB")
        W, H = base.size
        frames = [base]
        dur = 0.0
    else:
        dur = info["dur"] or 6.0
        frames = [CT.grab(a.src, dur * p) for p in (0.05, 0.5, 0.95)]
        frames = [f for f in frames if f is not None]
    if not W or not H:
        sys.exit("读不到尺寸：%s" % a.src)
    if not frames:
        sys.exit("抽不到画面")

    # 显式边距：跳过检测，批量时用这个（检测会被浅色地面误判）
    if a.right or a.bottom:
        cut_r, cut_b = max(0, a.right), max(0, a.bottom)
        cw, ch = W - cut_r, H - cut_b
        if cw <= 100 or ch <= 100:
            sys.exit("裁切后尺寸异常 %dx%d" % (cw, ch))
        tw, th = [int(v) for v in (a.size or "%dx%d" % (W, H)).lower().split("x")]
        vf = ("crop=%d:%d:0:0,scale=%d:%d:force_original_aspect_ratio=increase"
              ":flags=lanczos,crop=%d:%d" % (cw, ch, tw, th, tw, th))
        cmd = [CT.FF, "-y", "-v", "error", "-i", a.src, "-vf", vf]
        cmd += ["-frames:v", "1"] if still else ["-c:v", "libx264", "-preset", "slow",
                                                 "-crf", "17", "-pix_fmt", "yuv420p", "-an"]
        cmd.append(a.out)
        subprocess.run(cmd, check=True)
        rep = dict(mode="margin", crop=dict(w=cw, h=ch, right=cut_r, bottom=cut_b),
                   out=a.out, size=[tw, th])
        print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json
              else "按固定边距裁：右 %d / 下 %d → %dx%d" % (cut_r, cut_b, tw, th))
        return

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
            if a.size:
                tw, th = [int(v) for v in a.size.lower().split("x")]
                subprocess.run([CT.FF, "-y", "-v", "error", "-i", a.src,
                                "-vf", "scale=%d:%d:flags=lanczos" % (tw, th),
                                "-frames:v", "1", a.out], check=True)
                print("已按 %dx%d 归一化到 %s" % (tw, th, a.out))
            else:
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
    tw, th = W, H
    if a.size:
        tw, th = [int(v) for v in a.size.lower().split("x")]
    if a.scale_back or a.size:
        # 用 cover 而不是拉伸：先放大到盖住目标，再居中裁，避免人形被横向拉胖
        vf += (",scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos"
               ",crop=%d:%d" % (tw, th, tw, th))

    cmd = [CT.FF, "-y", "-v", "error", "-i", a.src, "-vf", vf]
    if still:
        cmd += ["-frames:v", "1"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "17",
                "-pix_fmt", "yuv420p", "-an"]
    cmd.append(a.out)
    subprocess.run(cmd, check=True)

    rep = dict(corner=best["corner"], bbox=best["bbox"], score=best["score"],
               crop=dict(w=cw, h=ch, x=cut_l, y=cut_t), out=a.out)

    # 复测
    if still:
        f2 = [Image.open(a.out).convert("RGB")]
    else:
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
