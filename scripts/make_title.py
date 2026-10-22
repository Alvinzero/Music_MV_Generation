#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把歌名/歌手排进画面帧，再由 zoompan 推镜 —— 片头标题卡。

    # 先只看位置（不渲视频）
    python scripts/make_title.py --src scene.png --title "手写的从前" --singer "周杰伦" \
        --cy-title 540 --still out/title_still.png --no-video

    # 确认后出视频
    python scripts/make_title.py --src scene.png --title "手写的从前" --singer "周杰伦" \
        --cy-title 505 --singer-y 292 --singer-size 40 --no-line \
        --video out/title.mp4

为什么要合成进帧、而不是走字幕轨：字必须和纸一起被推近。见
`references/subtitle-layout.md` 第七节「片头：歌曲信息要长在画面里」。

三条硬指标（脚本会打印实测值）：
  ① 歌名中心 ≈ 画布中心（±20px 更好；画布中线 540）
  ② 标题宽度占画面 40–55%
  ③ 缩到 375px 宽还能读
"""
import argparse
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FF = shutil.which("ffmpeg") or r"D:/workbuddy/runtime/ffmpeg/ffmpeg.exe"
# 字体默认跟着脚本走，不依赖 cwd —— 否则从工程目录跑就找不到字体
FONT_DEFAULT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts",
    "MVSerifSC-SemiBold.ttf"))


def text_w(draw, text, font, tracking):
    return sum(draw.textlength(c, font=font) for c in text) + tracking * (len(text) - 1)


def draw_tracked(draw, xy, text, font, tracking, fill):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def bbox_by_ink(path, ink, tol=45, min_px=60, x0=0.22, x1=0.78):
    """按墨色相似度量标题行段 —— 灰阶阈值会被纸雕阴影带偏。"""
    im = np.asarray(Image.open(path).convert("RGB"), dtype=int)
    h, w = im.shape[:2]
    band = im[:, int(w * x0):int(w * x1)]
    d = np.abs(band - np.array(ink)).sum(2)
    rows = np.where((d < tol).sum(1) > min_px)[0]
    if not len(rows):
        return None
    return rows.min(), rows.max(), (rows.min() + rows.max()) / 2, w


def render_push(a, still, W, H):
    """把静帧推成片头片段（zoompan，锚在画面中心）。"""
    step = (a.zoom - 1.0) / a.frames
    subprocess.run([FF, "-y", "-v", "error", "-loop", "1", "-i", still,
                    "-vf", ("scale=%d:%d:flags=lanczos,"
                            "zoompan=z='min(1.0+%.6f*on,%.4f)':"
                            "x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
                            "d=%d:s=%dx%d:fps=%g,format=yuv420p"
                            % (W * 2, H * 2, step, a.zoom, a.frames, W, H, a.fps)),
                    "-t", "%.3f" % (a.frames / a.fps), "-r", "%g" % a.fps,
                    "-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf),
                    "-an", a.video], check=True)
    print("写入", a.video)
    print("提醒：母版要用 trim=start_frame=%d 接，且改完片头必须重制无字幕母版" % a.frames)


def vertical_title(a, base, ink, W, H):
    """竖排标题（纸幡/竖招牌）。

    字号在 `--area` 里自动定：先把"n 个字 + 字距 + 署名"算进去，
    **上下各留出至少 6% 载体高的空**。算满高度会把首字顶到纸边——
    这是片头最常见的返工点，所以这里强制留白，并在结束时打印实测值。
    """
    if not a.area:
        sys.exit("--vertical 需要 --area x0,y0,x1,y1（载体的范围）")
    x0, y0, x1, y1 = [float(v) for v in a.area.split(",")]
    area_w, area_h = x1 - x0, y1 - y0
    n = len(a.title)
    GAP_R = 0.06
    reserve = 0.95 if a.singer else 0.20
    fs = int(min(area_w * 0.95, area_h / (n + (n - 1) * GAP_R + reserve)))

    def block_of(size):
        g = int(size * GAP_R)
        bh = n * size + (n - 1) * g
        sh = int(size * 0.22) + max(18, int(size * 0.33)) if a.singer else 0
        return bh, sh

    # 强制留白：上下各 ≥ 6% 载体高。不够就降字号，一直到装得下为止。
    # 这一步是防"首字顶到纸边"的根本办法——先算满再靠人眼发现已经晚了。
    while fs > 26:
        bh, sh = block_of(fs)
        if (area_h - bh - sh) / 2 >= area_h * 0.065:
            break
        fs -= 1

    f_t = ImageFont.truetype(a.font, fs)
    gap = int(fs * GAP_R)
    block_h = n * fs + (n - 1) * gap
    f_s = ImageFont.truetype(a.font, max(18, int(fs * 0.33))) if a.singer else None
    singer_block = int(fs * 0.22) + f_s.size if f_s else 0
    total = block_h + singer_block
    top = y0 + (area_h - total) / 2          # 居中 → 上下留白自动相等
    cx = (x0 + x1) / 2

    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    y = top
    for ch in a.title:
        bb = d.textbbox((0, 0), ch, font=f_t)
        d.text((cx - (bb[2] - bb[0]) / 2 - bb[0], y - bb[1]), ch, font=f_t, fill=255)
        y += fs + gap
    if f_s:
        sw = text_w(d, a.singer, f_s, 10)
        sx, sy = cx - sw / 2, top + block_h + int(fs * 0.22)
        for ch in a.singer:
            d.text((sx, sy), ch, font=f_s, fill=255)
            sx += d.textlength(ch, font=f_s) + 10

    # 字压进纸：纸纹调制墨的透明度 + 2px 压印阴影 + 0.6px 柔化
    g = np.asarray(base.convert("L").filter(ImageFilter.GaussianBlur(1.2)),
                   dtype=np.float32) / 255.0
    mod = np.clip((g - 0.45) * 1.6 + 0.82, 0.66, 1.0)
    m = np.asarray(mask, dtype=np.float32) / 255.0 * mod
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(0.6)), dtype=np.float32) / 255.0

    out = np.asarray(base.convert("RGB"), dtype=np.float32)
    shadow = np.clip(np.roll(m, 2, axis=0) * 0.55, 0, 1)[..., None]
    out = out * (1 - 0.35 * shadow)
    al = (m * 0.99)[..., None]
    out = out * (1 - al) + np.array(ink, dtype=np.float32) * al
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(a.still)

    # 自检：拿实际着墨行来量，不用阈值猜
    ys, xs = np.where(m > 0.35)
    if len(ys):
        t_m, b_m = ys.min() - y0, y1 - ys.max()
        fill = (ys.max() - ys.min()) / area_h
        print("竖排 %d 字 字号 %d  占载体高 %.1f%%" % (n, fs, fill * 100))
        print("首字距载体顶 %.0fpx（%.1f%%）  末字/署名距底 %.0fpx（%.1f%%）"
              % (t_m, t_m / area_h * 100, b_m, b_m / area_h * 100))
        print("字块中心 x=%.0f（载体中线 %.0f，差 %+.0f）"
              % ((xs.min() + xs.max()) / 2, cx, (xs.min() + xs.max()) / 2 - cx))
        if t_m < area_h * 0.06 or b_m < area_h * 0.06:
            print("  [警告] 上下留白不足 6%，首字会顶到载体边缘")
        if fs < 40:
            print("  [警告] 字号已降到 %d，载体偏小——建议加高载体或减少字数" % fs)
    print("写入", a.still)
    if not a.no_video:
        render_push(a, a.still, W, H)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="无字场景图（1920x1080 或任意，会按原尺寸排版）")
    ap.add_argument("--title", required=True)
    ap.add_argument("--singer", default="")
    ap.add_argument("--font", default=FONT_DEFAULT)
    ap.add_argument("--cy-title", dest="cy_title", type=int, default=540,
                    help="歌名文字块的中心 y；画布高 1080 时 540 为正中")
    ap.add_argument("--size", type=int, default=190, help="歌名字号")
    ap.add_argument("--tracking", type=float, default=22, help="字距")
    ap.add_argument("--singer-y", dest="singer_y", type=int, default=0,
                    help="署名 y（0 = 紧跟在歌名下方）")
    ap.add_argument("--singer-size", dest="singer_size", type=int, default=44)
    ap.add_argument("--singer-gap", dest="singer_gap", type=int, default=40)
    ap.add_argument("--ink", default="48,34,24", help="歌名墨色 r,g,b")
    ap.add_argument("--no-line", dest="no_line", action="store_true", help="不画歌名上方的分隔线")
    ap.add_argument("--still", default="out/title_still.png")
    ap.add_argument("--video", default="out/title.mp4")
    ap.add_argument("--frames", type=int, default=125, help="片头帧数（24fps 下 125 ≈ 5.21s）")
    ap.add_argument("--fps", type=float, default=24)
    ap.add_argument("--zoom", type=float, default=1.07, help="推镜终点倍率")
    ap.add_argument("--crf", type=int, default=16)
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--vertical", action="store_true",
                    help="竖排（纸幡/竖招牌）；必须配 --area，会自动留出上下边距")
    ap.add_argument("--area", default="",
                    help="载体范围 x0,y0,x1,y1（竖排时用，字块在这个框内自动定号并居中）")
    a = ap.parse_args()

    ink = tuple(int(v) for v in a.ink.split(","))
    base = Image.open(a.src).convert("RGBA")
    W, H = base.size
    mid = H / 2.0

    if a.vertical:
        return vertical_title(a, base, ink, W, H)

    f_title = ImageFont.truetype(a.font, a.size)
    f_sing = ImageFont.truetype(a.font, a.singer_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw = text_w(probe, a.title, f_title, a.tracking)
    sw = text_w(probe, a.singer, f_sing, 14) if a.singer else 0

    title_y = a.cy_title - int(a.size * 0.52)
    singer_y = a.singer_y if a.singer_y else title_y + int(a.size * 1.02) + a.singer_gap
    line_y = title_y - 34

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    draw_tracked(ds, ((W - tw) / 2 + 6, title_y + 8), a.title, f_title, a.tracking, ink + (130,))
    layer = Image.alpha_composite(layer, sh.filter(ImageFilter.GaussianBlur(9)))

    d = ImageDraw.Draw(layer)
    draw_tracked(d, ((W - tw) / 2, title_y), a.title, f_title, a.tracking, ink + (255,))
    if a.singer:
        draw_tracked(d, ((W - sw) / 2, singer_y), a.singer, f_sing, 14, (66, 48, 34, 255))
    if not a.no_line:
        d.line([((W - 96) / 2, line_y), ((W + 96) / 2, line_y)], fill=(96, 72, 52, 150), width=2)

    out = Image.alpha_composite(base, layer).convert("RGB")
    out.save(a.still)

    m = bbox_by_ink(a.still, ink)
    if m:
        y0, y1, cy, _ = m
        print("歌名 y=%d..%d 中心 %d（画布中线 %.0f，差 %+.0f）  占宽 %.1f%%"
              % (y0, y1, cy, mid, cy - mid, tw / W * 100))
        if abs(cy - mid) > 40:
            print("  [警告] 偏离画布中线超过 40px")
        if not 0.40 <= tw / W <= 0.58:
            print("  [警告] 标题占宽 %.1f%%，超出 40–58%%" % (tw / W * 100))
    print("写入", a.still)

    if a.no_video:
        return
    render_push(a, a.still, W, H)


if __name__ == "__main__":
    main()
