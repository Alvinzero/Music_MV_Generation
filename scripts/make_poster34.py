#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""横版作品转 3:4 主页封面：两种做法，保住整个 16:9 画面。

    python scripts/make_poster34.py --src images/s02.png --out cover/a.png \
        --title "无人知晓的我" --artist "A-Lin" --style postcard

    python scripts/make_poster34.py --src images/s02.png --out cover/b.png \
        --title "无人知晓的我" --artist "A-Lin" --style blur

为什么需要它：抖音个人页网格固定 3:4，16:9 不单独传封面时，平台拿首帧居中裁，
**切掉 58% 宽度**，标题横跨整幅就会被切断。

两种做法都不裁掉画面：
  blur      16:9 满宽居中，上下用同图模糊+压暗补满，标题压在下部模糊带（电影海报感）
  postcard  16:9 当照片贴在米色纸上，四周留白，标题印在纸面下方（出版物感，网格最整齐）
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "..", "assets", "fonts", "MVSerifSC-SemiBold.ttf")
W, H = 1080, 1440
CREAM, INK = (242, 226, 196), (43, 33, 24)


def frame(path, wm_cut=0):
    im = Image.open(path).convert("RGB")
    if wm_cut:
        im = im.crop((0, 0, im.width, im.height - wm_cut))
    w = W                                  # 满宽，高度按原比例
    h = int(w * im.height / im.width)
    return im.resize((w, h), Image.LANCZOS)


def blur_bg(im, blur=34, dark=0.55):
    s = max(W / im.width, H / im.height)
    b = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    b = b.crop(((b.width - W) // 2, (b.height - H) // 2,
                (b.width - W) // 2 + W, (b.height - H) // 2 + H))
    b = b.filter(ImageFilter.GaussianBlur(blur))
    return Image.fromarray((np.asarray(b, dtype=np.float32) * (1 - dark)).astype(np.uint8))


def put(canvas, text, fs, cy, color=CREAM, tracking=9, alpha=0.96, shadow=0.7, font_path=FONT):
    f = ImageFont.truetype(font_path, fs)
    d0 = ImageDraw.Draw(Image.new("L", (10, 10)))
    total = sum(d0.textlength(c, font=f) for c in text) + tracking * (len(text) - 1)
    m = Image.new("L", (W, H), 0)
    d, x = ImageDraw.Draw(m), W / 2 - total / 2
    for c in text:
        d.text((x, cy - fs * 0.70), c, font=f, fill=255)
        x += d0.textlength(c, font=f) + tracking
    g = np.asarray(canvas.convert("L").filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32) / 255.0
    mm = np.asarray(m, dtype=np.float32) / 255.0 * np.clip((g - 0.40) * 1.45 + 0.88, 0.72, 1.0)
    sh = np.asarray(m.filter(ImageFilter.GaussianBlur(10)), dtype=np.float32) / 255.0
    o = np.asarray(canvas, dtype=np.float32)
    a = (sh * shadow)[..., None]
    o = o * (1 - a) + np.array([6, 7, 10], dtype=np.float32) * a
    a = (mm * alpha)[..., None]
    o = o * (1 - a) + np.array(color, dtype=np.float32) * a
    return Image.fromarray(np.clip(o, 0, 255).astype(np.uint8)), total


def rule(img, y, w=220, color=(236, 214, 178), alpha=120):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(lay).line([(W / 2 - w / 2, y), (W / 2 + w / 2, y)], fill=color + (alpha,), width=2)
    return Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")


def style_blur(scene, title, artist):
    fh = int(W * scene.height / scene.width)
    canvas = blur_bg(scene)
    top = (H - fh) // 2
    canvas.paste(scene, (0, top))
    y0 = top + fh
    ys = np.arange(H, dtype=np.float32)[:, None, None]
    t = np.clip((ys - (y0 - 40)) / 260.0, 0, 1)
    g = (np.sin(t * np.pi / 2) ** 1.2) * 0.55
    o = np.asarray(canvas, dtype=np.float32)
    canvas = Image.fromarray(np.clip(o * (1 - g), 0, 255).astype(np.uint8))
    cy = y0 + (H - y0) // 2 - 10
    canvas = put(canvas, title, 104, cy, tracking=8)[0]
    canvas = rule(canvas, cy + 74, 200, alpha=110)
    canvas = put(canvas, artist, 34, cy + 118, tracking=12, alpha=0.80, shadow=0.3)[0]
    return canvas


def style_postcard(scene, title, artist):
    pad = 54
    fw = W - pad * 2
    fh = int(fw * scene.height / scene.width)
    total = fh + 96 + 116 + 70 + 40          # 照片 + 间隙 + 标题 + 细线 + 署名
    top = max(60, (H - total) // 2)          # 整组垂直居中，上下留白相等

    paper = Image.new("RGB", (W, H), (238, 229, 210))
    n = np.random.RandomState(5).normal(0, 4.5, (H, W, 1)).repeat(3, 2)
    paper = Image.fromarray(np.clip(np.asarray(paper, dtype=np.float32) + n, 0, 255).astype(np.uint8))

    shot = scene.resize((fw, fh), Image.LANCZOS)
    sh = Image.new("L", (fw + 40, fh + 40), 0)
    ImageDraw.Draw(sh).rectangle([20, 26, fw + 20, fh + 20], fill=120)
    paper.paste(Image.new("RGB", (fw + 40, fh + 40), (60, 48, 34)),
                (pad - 20, top - 20), sh.filter(ImageFilter.GaussianBlur(12)))
    paper.paste(shot, (pad, top))

    cy = top + fh + 96
    paper = put(paper, title, 96, cy, color=INK, tracking=10, alpha=0.95, shadow=0.16)[0]
    paper = rule(paper, cy + 70, 240, color=(150, 78, 58), alpha=150)
    if artist:
        paper = put(paper, artist, 30, cy + 110, color=(92, 70, 54), tracking=6,
                    alpha=0.85, shadow=0.05)[0]
    return paper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", default="")
    ap.add_argument("--style", choices=["blur", "postcard"], default="postcard")
    ap.add_argument("--wm-cut", dest="wm_cut", type=int, default=0,
                    help="先切掉底部多少像素的水印（ImageGen 约 62）")
    ap.add_argument("--no-auto-wm", dest="auto_wm", action="store_false",
                    help="关掉自动检水印")
    a = ap.parse_args()

    cut = a.wm_cut
    if a.auto_wm and not cut:
        try:
            import check_title as CT
            im = Image.open(a.src).convert("RGB")
            fr = [im]
            best = 0.0
            for name, box in CT.corners(im).items():
                sc_, bb = CT.wm_score(im, box)
                if sc_ > best and bb and name in ("右下", "下"):
                    best, cut = sc_, min(im.height - bb[1] + 12, int(im.height * 0.12))
            if best < 0.35:
                cut = 0
        except Exception:
            cut = 0

    sc = frame(a.src, cut)
    img = style_postcard(sc, a.title, a.artist) if a.style == "postcard" \
        else style_blur(sc, a.title, a.artist)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    img.save(a.out)
    img.resize((1280, int(1280 * H / W)), Image.LANCZOS).save(
        a.out.replace(".png", "_1280.jpg"), quality=92)
    img.resize((375, int(375 * H / W)), Image.LANCZOS).save(
        a.out.replace(".png", "_chk375.png"))
    print("写入 %s（+ _1280.jpg / _chk375.png）  %s" % (a.out, a.style))


if __name__ == "__main__":
    main()
