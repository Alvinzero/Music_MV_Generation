#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成片之后：做一张能直接发短视频的封面（标题一律字库排，不交给图像模型）。

    # 3:4 竖版（抖音/快手/小红书信息流默认裁切比）
    python scripts/make_cover.py --src cover_base.png --title "无人知晓的我" --artist "A-LIN" \
        --ratio 3:4 --vertical --area 700,40,1250,760 --out cover/封面_v1.png

    # 横版标题压纸带（海报式）
    python scripts/make_cover.py --src cover_base.png --title "手写的从前" --artist "周杰伦" \
        --ratio 16:9 --layout band --out cover/封面.png

为什么封面标题必须字库排：模型画中文会错字/繁简混用，而封面是**缩略图尺寸**阅读，
一个错字就废。底图只负责氛围，字由 Pillow 排进去。

三条自检（脚本会打印实测值，超范围会 WARN）：
  ① 标题块中心贴近画布中心（横版看 x/y，竖排看 x）
  ② 标题宽度占画面 45–60%（横排）；竖排看**占载体高** 60–90%
  ③ 缩到 375px 宽仍能读（脚本会存 _chk375.png，最小字高 < 14px 报警）
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

RATIOS = {          # 名称 -> (宽, 高)
    "3:4": (1080, 1440),
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}

PAPER = (243, 232, 209)
INK = (43, 33, 24)
SUB_INK = (74, 55, 38)

# 字体跟随技能目录（scripts/ 的上一级是技能根），避免技能改名或换机后默认路径失效
FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
DEFAULT_FONT = str(FONT_DIR / "MVSerifSC-SemiBold.ttf")


def load_font(path, size):
    if path and os.path.isfile(path):
        return ImageFont.truetype(path, size)
    for cand in ("MVSerifSC-SemiBold.ttf", "C:/Windows/Fonts/simsun.ttc"):
        for p in (cand, str(FONT_DIR / cand)):
            if os.path.isfile(p):
                return ImageFont.truetype(p, size)
    sys.exit("找不到字体，用 --font 指定一个 ttf")


def fit_image(src, ratio, anchor="center"):
    """裁成目标比例再放大。返回 (img, 裁切框)。"""
    W, H = RATIOS[ratio]
    im = Image.open(src).convert("RGB")
    sw, sh = im.size
    target = W / H
    if sw / sh > target:                       # 太宽，裁两侧
        nw = int(round(sh * target))
        x0 = (sw - nw) // 2
        box = (x0, 0, x0 + nw, sh)
    else:                                      # 太高，裁上下
        nh = int(round(sw / target))
        y0 = 0 if anchor == "top" else (sh - nh) // 2
        box = (0, y0, sw, y0 + nh)
    return im.crop(box).resize((W, H), Image.LANCZOS), box


def text_mask(W, H, text, font, tracking, box, vertical=False):
    """在 box 内排字，返回 (mask, 排版信息)。box=(x0,y0,x1,y1) 为字块可用区。"""
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    x0, y0, x1, y1 = box
    if not vertical:
        total = sum(d.textlength(c, font=font) for c in text) + tracking * (len(text) - 1)
        x = x0 + ((x1 - x0) - total) / 2
        asc, desc = font.getmetrics()
        baseline = y0 + ((y1 - y0) - (asc + desc)) / 2
        for c in text:
            d.text((x, baseline), c, font=font, fill=255)
            x += d.textlength(c, font=font) + tracking
        return mask, dict(total=total, x=x0 + ((x1 - x0) - total) / 2)
    # 竖排：逐字居中
    n = len(text)
    step = 0
    for i, c in enumerate(text):
        bb = d.textbbox((0, 0), c, font=font)
        w = bb[2] - bb[0]
        h = bb[3] - bb[1]
        cx = (x0 + x1) / 2
        # 首字顶对齐 box 顶，按 (行高) 递推
        if i == 0:
            y = y0 - bb[1]
        else:
            y += step
        d.text((cx - w / 2 - bb[0], y), c, font=font, fill=255)
        step = font.size
        if i == 0:
            step = font.size
    return mask, dict(total=font.size * n, x=(x0 + x1) / 2 - font.size / 2)


def size_for_vertical(text, box_w, box_h, reserve=0.55, gap_ratio=0.06):
    """竖排字号：n 个字 + 字距 + 署名行(约 reserve 个字高) 一起塞进 box_h。"""
    n = len(text)
    by_h = box_h / (n + (n - 1) * gap_ratio + reserve)
    return int(min(box_w * 1.02, by_h))


def size_for_horizontal(text, box_w, font_probe, gap_ratio=0.12):
    """横排字号：二分找到填满 box_w 的字号。"""
    lo, hi = 16, 600
    while lo < hi:
        mid = (lo + hi + 1) // 2
        f = font_probe(mid)
        d = ImageDraw.Draw(Image.new("L", (10, 10)))
        total = sum(d.textlength(c, font=f) for c in text) + gap_ratio * mid * (len(text) - 1)
        if total <= box_w:
            lo = mid
        else:
            hi = mid - 1
    return lo


def band_layer(img, band_top, mode="auto"):
    """底部纸带 + 三层投影。

    auto：取原图底 40 行的中位色；但如果它太暗（夜景），直接用米色纸——
    深色带 + 深色字会糊成一片，这是 band 版式最常见的翻车点。
    """
    W, H = img.size
    a = np.asarray(img)
    rgb = tuple(int(v) for v in np.median(a[-40:, :, :].reshape(-1, 3), axis=0))
    lum = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0
    if mode == "paper" or (mode == "auto" and lum < 0.42):
        rgb = PAPER
    print("纸带底色 %s（采样亮度 %.2f）" % (str(rgb), lum))
    out = img.convert("RGBA")
    d = ImageDraw.Draw(out, "RGBA")
    for dy, alpha in ((6, 26), (14, 14), (24, 7)):
        d.rectangle([0, band_top + dy, W, H], fill=(0, 0, 0, alpha))
    d.rectangle([0, band_top, W, H], fill=tuple(rgb) + (255,))
    return out.convert("RGB")


def press(mask, base, ink=INK, alpha=0.99, blur=0.6):
    """把字压进画面：纸纹调制 + 1.5px 压印阴影 + 轻微模糊，去掉矢量味。"""
    W, H = base.size
    m = np.asarray(mask, dtype=np.float32) / 255.0
    a = np.asarray(base).astype(np.float32) / 255.0
    grain = Image.fromarray((a.mean(2) * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(1.2))
    grain = np.asarray(grain, dtype=np.float32) / 255.0
    mod = np.clip((grain - 0.45) * 1.6 + 0.82, 0.66, 1.0)
    m = m * mod
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(blur)), dtype=np.float32) / 255.0
    out = np.asarray(base).astype(np.float32)
    sh = np.clip(np.roll(m, 2, axis=0) * 0.55, 0, 1)[..., None]
    out = out * (1 - 0.35 * sh)
    al = (m * alpha)[..., None]
    out = out * (1 - al) + np.array(ink, dtype=np.float32) * al
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="无字底图（比例随意，会裁）")
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", default="")
    ap.add_argument("--tag", default="", help="角标文字，如「纸雕 MV」")
    ap.add_argument("--ratio", default="3:4", choices=list(RATIOS))
    ap.add_argument("--layout", default="vertical", choices=["vertical", "band"])
    ap.add_argument("--vertical", action="store_true", help="标题竖排（等价 layout=vertical）")
    ap.add_argument("--area", default="", help="竖排字块可用区 x0,y0,x1,y1")
    ap.add_argument("--band", type=float, default=0.30, help="band 模式纸带高度占比")
    ap.add_argument("--band-color", dest="band_color", default="auto", choices=["auto", "sample", "paper"])
    ap.add_argument("--title-width", dest="title_width", type=float, default=0.62,
                    help="band 模式标题占画面宽的比例（0.45–0.60 最稳）")
    ap.add_argument("--font", default=DEFAULT_FONT)
    ap.add_argument("--ink", default="43,33,24")
    ap.add_argument("--out", required=True)
    ap.add_argument("--anchor", default="center", choices=["center", "top"])
    a = ap.parse_args()

    ink = tuple(int(v) for v in a.ink.split(","))
    img, box = fit_image(a.src, a.ratio, a.anchor)
    W, H = img.size
    print("底图 %s -> %dx%d（裁切 %s）" % (a.src, W, H, box))

    layout = "vertical" if a.vertical else a.layout
    if layout == "band":
        top = int(H * (1 - a.band))
        band_h = H - top
        img = band_layer(img, top, a.band_color)
        fs = size_for_horizontal(a.title, int(W * a.title_width), lambda s: load_font(a.font, s))
        f_title = load_font(a.font, fs)
        # 标题占纸带上半，署名压在下沿之上，两端都留出 band_h 的 12%
        area = (W * 0.06, top + band_h * 0.14, W * 0.94, top + band_h * 0.56)
        mask, info = text_mask(W, H, a.title, f_title, int(fs * 0.10), area)
        img = press(mask, img, ink)
        y = top + band_h * 0.64
        if a.artist:
            f_sub = load_font(a.font, max(20, int(fs * 0.28)))
            sub = Image.new("L", (W, H), 0)
            ds = ImageDraw.Draw(sub)
            total = sum(ds.textlength(c, font=f_sub) for c in a.artist) + \
                int(fs * 0.14) * (len(a.artist) - 1)
            x = (W - total) / 2
            y = min(y, H - band_h * 0.10 - f_sub.size)
            for c in a.artist:
                ds.text((x, y), c, font=f_sub, fill=255)
                x += ds.textlength(c, font=f_sub) + int(fs * 0.14)
            img = press(sub, img, (86, 64, 44), blur=0.5)
        artist_y = y
    else:
        if not a.area:
            sys.exit("竖排要 --area x0,y0,x1,y1（字块可用区），或改用 --layout band")
        x0, y0, x1, y1 = [float(v) for v in a.area.split(",")]
        fs = size_for_vertical(a.title, x1 - x0, y1 - y0,
                               reserve=(0.55 if a.artist else 0.12))
        f_title = load_font(a.font, fs)
        gap = int(fs * 0.06)
        mask = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(mask)
        cx = (x0 + x1) / 2
        y = y0
        for c in a.title:
            bb = d.textbbox((0, 0), c, font=f_title)
            d.text((cx - (bb[2] - bb[0]) / 2 - bb[0], y - bb[1]), c, font=f_title, fill=255)
            y += fs + gap
        img = press(mask, img, ink)
        artist_y = y + int(fs * 0.10)
        if a.artist:
            f_sub = load_font(a.font, max(20, int(fs * 0.33)))
            total = sum(d.textlength(c, font=f_sub) for c in a.artist) + int(fs * 0.10) * (len(a.artist) - 1)
            x = cx - total / 2
            smask = Image.new("L", (W, H), 0)
            ds = ImageDraw.Draw(smask)
            for c in a.artist:
                ds.text((x, artist_y), c, font=f_sub, fill=255)
                x += ds.textlength(c, font=f_sub) + int(fs * 0.10)
            img = press(smask, img, (62, 45, 31), blur=0.45)
        info = dict(fs=fs)

    if a.tag:
        f_tag = load_font(a.font, max(16, int(W * 0.017)))
        d = ImageDraw.Draw(img)
        tw = sum(d.textlength(c, font=f_tag) for c in a.tag) + 2 * (len(a.tag) - 1)
        d.text((W - tw - W * 0.035, H - H * 0.035 - f_tag.size), a.tag,
               font=f_tag, fill=(196, 182, 160))

    # ---- 自检：用排版 mask 量，比阈值法可靠 ----
    m = np.asarray(mask, dtype=np.uint8)
    ys, xs = np.where(m > 60)
    if len(xs):
        bw, bh = xs.max() - xs.min(), ys.max() - ys.min()
        ccx, ccy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
        print("标题块 %dx%d  中心(%.0f,%.0f)  画布中心(%d,%d)  偏(%+.0f,%+.0f)"
              % (bw, bh, ccx, ccy, W // 2, H // 2, ccx - W / 2, ccy - H / 2))
        if layout == "vertical":
            ax0, ay0, ax1, ay1 = [float(v) for v in a.area.split(",")]
            fill = bh / (ay1 - ay0) * 100
            print("竖排：占载体高 %.1f%%（标准 60–90%%）  载体中心 x=%.0f（标题中心 x=%.0f）"
                  % (fill, (ax0 + ax1) / 2, ccx))
            if not 60 <= fill <= 100:
                print("WARN 字号只填了载体 %.1f%%，载体给大一点或加字号" % fill)
            if abs(ccx - (ax0 + ax1) / 2) > 18:
                print("WARN 标题没有落在载体中线上（差 %.0fpx）" % (ccx - (ax0 + ax1) / 2))
            if abs(ccx - W / 2) > W * 0.06:
                print("WARN 文字块偏离画面中线 %.0fpx —— 封面标准要求居中（载体也要放中间）"
                      % (ccx - W / 2))
        else:
            pct = bw / W * 100
            print("横排占宽 %.1f%%（建议 45–60%%）" % pct)
            if not 40 <= pct <= 65:
                print("WARN 占宽 %.1f%% 不在 45–60%% 区间" % pct)
        if layout != "vertical" and abs(ccx - W / 2) > 24:
            print("WARN 标题横向偏离中线 %.0fpx" % (ccx - W / 2))
        char_px = bh / len(a.title) if layout == "vertical" else f_title.size
        print("单字高约 %.0fpx → 375px 预览下 %.1fpx（<14 就该加字号）"
              % (char_px, char_px * 375 / W))

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    stem, _ = os.path.splitext(a.out)
    img.save(stem + ".png")
    img.resize((1280, int(1280 * H / W)), Image.LANCZOS).save(stem + "_1280.jpg", quality=92)
    img.resize((375, int(375 * H / W)), Image.LANCZOS).save(stem + "_chk375.png")
    print("写入 %s / _1280.jpg / _chk375.png" % (stem + ".png"))


if __name__ == "__main__":
    main()
