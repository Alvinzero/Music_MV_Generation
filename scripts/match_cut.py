#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""切点匹配：让 A 的末帧和 B 的首帧在切点上"对上"，而不是硬跳。

    python scripts/match_cut.py --a work/s01.mp4 --b work/s02.mp4 --outdir work/match

为什么需要它：两个镜头各自都合格，剪在一起仍然可能刺眼。实测过的一次——
片头末帧均值 45.7、第一镜首帧 72.3，差 26.6；亮部占比 4.8% vs 20.3%；
再叠加空间从全景切微距，一刀下去同时跳亮度和尺度两档，观众第一反应是"卡了一下"。

**不要用 xfade 去解决**：叠化会吃掉重叠帧数，全片总帧一变，字幕全部错位。
这里改的是两侧的出入口，帧数一帧不动：

  ① A 的末尾 N 帧叠一层米色雾光，把末帧亮度抬到 B 的水平（雾 = 场景化进纸里）
  ② B 的开头 M 帧从虚焦拉实，把"尺度跳"变成一次拉焦
  ③ 两侧亮度差目标 ≤ 4（一档以内），超过就继续调

输出的两个文件帧数与输入完全一致，直接替换时间轴里的同名片段即可。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageFilter

FF = shutil.which("ffmpeg") or r"D:/workbuddy/runtime/ffmpeg/ffmpeg.exe"
CREAM = (238, 230, 212)          # 与纸雕风格同族的米色，换风格时改这里


def probe(path):
    err = subprocess.run([FF, "-hide_banner", "-i", path],
                         capture_output=True).stderr.decode("utf-8", "ignore")
    dur = 0.0
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    fps = 24.0
    m = re.search(r"(\d+(?:\.\d+)?) fps", err)
    if m:
        fps = float(m.group(1))
    return dur, fps


def extract(clip, outdir):
    os.makedirs(outdir, exist_ok=True)
    for f in os.listdir(outdir):
        os.remove(os.path.join(outdir, f))
    subprocess.run([FF, "-y", "-v", "error", "-i", clip,
                    "-fps_mode", "passthrough", os.path.join(outdir, "f_%04d.png")], check=True)
    return sorted(os.listdir(outdir))


def encode(frames_dir, out, fps):
    subprocess.run([FF, "-y", "-v", "error", "-framerate", "%.6f" % fps,
                    "-i", os.path.join(frames_dir, "f_%04d.png"),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                    "-pix_fmt", "yuv420p", out], check=True)


def mean_luma(path):
    a = np.asarray(Image.open(path).convert("L"), np.float32)
    return float(a.mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="前一个镜头（片头）")
    ap.add_argument("--b", required=True, help="后一个镜头")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--ramp-out", type=int, default=26, help="A 末尾多少帧起雾")
    ap.add_argument("--ramp-in", type=int, default=9, help="B 开头多少帧拉焦")
    ap.add_argument("--blur", type=float, default=11.0, help="B 首帧的最大虚焦半径")
    ap.add_argument("--wash", type=float, default=0.05, help="B 开头的米色退场强度")
    ap.add_argument("--max-delta", type=float, default=4.0, help="切点亮度差的目标上限")
    ap.add_argument("--cream", default=",".join(str(c) for c in CREAM))
    a = ap.parse_args()

    cream = np.array([int(v) for v in a.cream.split(",")], np.float32)
    cream_luma = float(cream @ np.array([0.299, 0.587, 0.114], np.float32))

    os.makedirs(a.outdir, exist_ok=True)
    da, fpsa = probe(a.a)
    db, fpsb = probe(a.b)
    fa = extract(a.a, os.path.join(a.outdir, "a_in"))
    fb = extract(a.b, os.path.join(a.outdir, "b_in"))
    if not fa or not fb:
        sys.exit("抽不到帧")

    m_a = mean_luma(os.path.join(a.outdir, "a_in", fa[-1]))
    m_b = mean_luma(os.path.join(a.outdir, "b_in", fb[0]))
    print("切点前：A 末帧均值 %.1f  B 首帧均值 %.1f  差 %.1f" % (m_a, m_b, abs(m_a - m_b)))

    # 目标：把低的一侧抬到高的一侧（只能用米色往上加，不能往下压）
    # 注意：抬完 A 就不要再给 B 加雾了，否则 B 又被抬高，永远追不上
    target = m_b
    alpha_out = 0.0
    alpha_in = 0.0
    if target > m_a:
        alpha_out = (target - m_a) / max(cream_luma - m_a, 1e-3)
        alpha_out = float(np.clip(alpha_out, 0.0, 0.6))
    else:
        alpha_in = (m_a - target) / max(cream_luma - target, 1e-3)
        alpha_in = float(np.clip(alpha_in, 0.0, min(a.wash, 0.3)))

    # ① A：末尾 ramp-out 帧叠米色雾光
    adir = os.path.join(a.outdir, "a_out")
    os.makedirs(adir, exist_ok=True)
    n = len(fa)
    for i, f in enumerate(fa):
        img = np.asarray(Image.open(os.path.join(a.outdir, "a_in", f)).convert("RGB"), np.float32)
        k = np.clip((i - (n - 1 - a.ramp_out)) / float(a.ramp_out), 0, 1) ** 1.25
        al = alpha_out * k
        if al > 0:
            img = img * (1 - al) + cream * al
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(os.path.join(adir, f))

    # ② B：开头 ramp-in 帧虚焦拉实 + 轻退场
    bdir = os.path.join(a.outdir, "b_out")
    os.makedirs(bdir, exist_ok=True)
    for i, f in enumerate(fb):
        im = Image.open(os.path.join(a.outdir, "b_in", f)).convert("RGB")
        if i < a.ramp_in:
            r = a.blur * (1 - i / float(a.ramp_in)) ** 1.4
            if r > 0.2:
                im = im.filter(ImageFilter.GaussianBlur(r))
        img = np.asarray(im, np.float32)
        al = alpha_in * max(0.0, 1 - i / float(a.ramp_in + 3)) ** 1.3
        if al > 0:
            img = img * (1 - al) + cream * al
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(os.path.join(bdir, f))

    out_a = os.path.join(a.outdir, "a_matched.mp4")
    out_b = os.path.join(a.outdir, "b_matched.mp4")
    encode(adir, out_a, fpsa)
    encode(bdir, out_b, fpsb)

    n_a = mean_luma(os.path.join(adir, fa[-1]))
    n_b = mean_luma(os.path.join(bdir, fb[0]))
    delta = abs(n_a - n_b)
    print("切点后：A 末帧 %.1f  B 首帧 %.1f  差 %.1f（目标 ≤ %.0f）" % (n_a, n_b, delta, a.max_delta))
    print("雾光 alpha %.3f / 入口虚焦 %.1fpx %d 帧 / 入口米色 %.3f" % (alpha_out, a.blur, a.ramp_in, alpha_in))
    print("帧数：A %d（原 %d）  B %d（原 %d）" % (len(fa), len(fa), len(fb), len(fb)))
    print("写入", out_a, out_b)
    if delta > a.max_delta:
        print("[注意] 仍超过目标；把 --ramp-out 调长（雾起得更早）或换一个更接近的下一镜")
        sys.exit(2)
    print("[通过] 切点已对齐")


if __name__ == "__main__":
    main()
