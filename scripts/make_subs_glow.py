#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无卡字幕：暖光字（画出"光从纸背透出来"的字，不用任何色块）。

适用的画面：**暗调、有明确光源、材质是纸/布/木**的片子。
不适合：亮调实拍、快剪口播（那些要描边+底条）。

    # 基础用法（统一琥珀辉光）
    python scripts/make_subs_glow.py --lines out/lines.json --out out/subs_glow.ass

    # 跟着镜头光走（需要能读到每一镜的静帧）
    python scripts/make_subs_glow.py --lines out/lines.json --out out/subs_glow.ass \
        --sheet "images/s%02d.png"

lines.json 里每条可选字段：
  shot —— 该句所在镜号，给了才会做"辉光跟镜头主色 + 亮处自适应柔影"
  x / y / fs / accent / emph / times —— 与 make_subs.py 一致

三条设计约束（改之前先读 references/subtitle-styles.md）：
  ① 无卡就必须有描边：`bord ≈ 0.030 * fs`，近黑，不然亮处直接消失
  ② 辉光只在暗处成立；亮处要按局部亮度补一层**散开的**柔影，不能是硬边色块
  ③ 去掉卡片后字号要放大 10–15%，否则视觉重量不够
"""
import argparse
import colorsys
import json

import numpy as np
from PIL import Image

CREAM = (242, 226, 196)
DARK = (10, 13, 20)
ACCENT = (239, 176, 94)
GLOW = (233, 169, 78)

# 十二套字幕配方里"无载体"的那几套（有载体的走 make_subs.py）。
# 默认 02 与历史参数完全一致，老工程重跑不会变样。
RECIPES = {
    "02-window-glow": dict(ink=(242, 226, 196), accent=(239, 176, 94), glow=(233, 169, 78),
                           ga=("68", "52"), gk=0.13, gmin=4.0, bk=0.030, bmin=1.6,
                           sp=3.0, sh=2, rise=8),
    "03-stone-carve": dict(ink=(232, 226, 214), accent=(232, 226, 214), glow=None,
                           ga=("FF", "FF"), gk=0.0, gmin=0.0, bk=0.045, bmin=3.0,
                           sp=12.0, sh=3, rise=10),
    "04-neon-bleed": dict(ink=(216, 96, 136), accent=(92, 176, 200), glow=(216, 96, 136),
                          ga=("60", "60"), gk=0.20, gmin=6.0, bk=0.020, bmin=1.4,
                          sp=2.0, sh=0, rise=0),
    "06-pencil-hand": dict(ink=(43, 43, 43), accent=(43, 43, 43), glow=None,
                           ga=("FF", "FF"), gk=0.0, gmin=0.0, bk=0.022, bmin=1.2,
                           sp=1.0, sh=0, rise=3, out=(243, 237, 226)),
    "07-metal-stamp": dict(ink=(201, 196, 186), accent=(201, 196, 186), glow=None,
                           ga=("FF", "FF"), gk=0.0, gmin=0.0, bk=0.010, bmin=1.0,
                           sp=4.0, sh=2, rise=0),
    "08-ink-colophon": dict(ink=(28, 26, 23), accent=(28, 26, 23), glow=None,
                            ga=("FF", "FF"), gk=0.0, gmin=0.0, bk=0.0, bmin=0.0,
                            sp=6.0, sh=0, rise=0),
    "11-spotlight": dict(ink=(255, 243, 214), accent=(255, 243, 214), glow=(255, 240, 208),
                         ga=("40", "40"), gk=0.22, gmin=8.0, bk=0.018, bmin=1.2,
                         sp=3.0, sh=1, rise=0),
    "12-mono-data": dict(ink=(155, 232, 200), accent=(155, 232, 200), glow=None,
                         ga=("FF", "FF"), gk=0.0, gmin=0.0, bk=0.0, bmin=0.0,
                         sp=1.5, sh=0, rise=0),
}
RCP = RECIPES["02-window-glow"]


def bgr(rgb):
    return "&H%02X%02X%02X&" % (rgb[2], rgb[1], rgb[0])


def bgr_a(rgb, alpha=0x00):
    return "&H%02X%02X%02X%02X" % (alpha, rgb[2], rgb[1], rgb[0])


def ts(t):
    return "%d:%02d:%05.2f" % (int(t // 3600), int(t % 3600 // 60), t % 60)


class Sheet:
    """按镜号读静帧，用来算"这个镜头的灯色"和"这句压在多亮的背景上"。"""

    def __init__(self, pattern):
        self.pat = pattern
        self._c = {}
        self._l = {}

    def _img(self, idx):
        if idx not in self._c:
            im = Image.open(self.pat % idx).convert("RGB")
            w, h = im.size
            if w > 1755:                       # 统一裁掉出图水印区
                im = im.crop((0, 0, 1755, 987))
            self._c[idx] = np.asarray(im, dtype=np.float32)
        return self._c[idx]

    def glow(self, idx):
        """整幅里最饱和的一小撮像素当'灯色'——字幕带本身常是暗部，判不出色相。"""
        a = self._img(idx)[::2, ::2].reshape(-1, 3)
        mx = a.max(1)
        sat = (mx - a.min(1)) / (mx + 1e-3)
        sel = a[sat > np.percentile(sat, 88)] if (sat > 0).any() else a
        r, g, b = sel.mean(0)
        hue = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360
        if max(r, g, b) < 55:
            return GLOW
        if 280 <= hue <= 350 and b > g * 0.9:
            return (214, 96, 140)              # 霓虹洋红
        if 170 <= hue <= 250 and b > r:
            return (92, 176, 200)              # 冷蓝/青
        return GLOW

    def band(self, idx, y, cx, w, h=120):
        """字幕实际占的那一小块有多亮（0–1）。不能用整行平均，两侧暗部会稀释高光。"""
        a = self._img(idx) / 255.0
        k = a.shape[0] / 1080.0
        y0 = int(max(0, min(a.shape[0] - 10, (y - h / 2) * k)))
        y1 = int(min(a.shape[0], y0 + h * k))
        x0 = int(max(0, min(a.shape[1] - 10, (cx - w / 2) * k)))
        x1 = int(min(a.shape[1], x0 + w * k))
        return float(np.percentile(a[y0:y1, x0:x1], 85))


def total_w(text, fs, emph):
    w = 0
    for i, _ in enumerate(text):
        f = int(round(fs * emph.get(i, 1.0)))
        w += f + (int(round(f * 0.08)) if i < len(text) - 1 else 0)
    return w


def head(font, sizes):
    st = []
    for fs in sizes:
        # BorderStyle=1：只有描边和投影，没有任何色块（"无卡"的关键）
        st.append("Style: G%d,%s,%d,%s,%s,%s,%s,0,0,0,0,100,100,%.1f,0,1,%.1f,%d,5,0,0,0,1"
                  % (fs, font, fs, bgr_a(RCP["ink"]), bgr_a(RCP["ink"]),
                     bgr_a(RCP.get("out", DARK)), bgr_a(DARK, 0x70),
                     RCP["sp"], max(RCP["bmin"], fs * RCP["bk"]), RCP["sh"]))
    st.append("Style: SH,%s,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
              "0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1" % font)
    return """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(styles="\n".join(st))


def emit(out, it, sheet, scale, glow_fixed, shadow_max):
    text = it["text"]
    n = len(text)
    times = it.get("times") or []
    if len(times) != n:
        step = (it["end"] - it["start"]) / max(1, n)
        times = [it["start"] + i * step for i in range(n)]
    fs = int(round(int(it.get("fs", 64)) * scale))
    cx = float(it.get("x", 960))
    cy = float(it.get("y", 900))
    emph = {int(k): float(v) for k, v in (it.get("emph") or {}).items()}
    accent = int(it.get("accent", -1))
    glow = glow_fixed
    if sheet and it.get("shot"):
        glow = sheet.glow(it["shot"])

    if sheet and it.get("shot"):
        lum = sheet.band(it["shot"], cy, cx, total_w(text, fs, emph))
        op = min(shadow_max, max(0.0, (lum - 0.16) * 1.05))
        if op > 0.04:
            padx, pady = 40, 20
            bw, bh = total_w(text, fs, emph), fs + pady * 2
            out.append(r'Dialogue: 0,%s,%s,SH,,0,0,0,,{\an7\pos(%.1f,%.1f)\p1\bord0\shad0'
                       r'\1c%s\3c%s\blur46\alpha&H%02X&\fad(200,260)}'
                       r'm 0 0 l %.1f 0 l %.1f %.1f l 0 %.1f z{\p0}'
                       % (ts(it["start"]), ts(it["end"] + 0.35), cx - bw / 2 - padx,
                          cy - bh / 2, bgr(DARK), bgr(DARK),
                          int(round(255 * (1 - op))), bw + padx * 2, bw + padx * 2, bh, bh))

    widths = []
    for i, _ in enumerate(text):
        f = int(round(fs * emph.get(i, 1.0)))
        widths.append((f, f + (int(round(f * 0.08)) if i < n - 1 else 0)))
    x = cx - sum(w for _, w in widths) / 2

    for i, ch in enumerate(text):
        f, w = widths[i]
        t_on = times[i]
        t_end = max(it["end"] + 0.30, t_on + 0.6)   # 整句一起收，已亮的字保持到句末
        px, py = x + w / 2, cy
        x += w
        is_acc = (i == accent)

        # 辉光层：更大更糊，只负责"光"（配方没有 glow 就整层跳过）
        if RCP["glow"] is not None:
            gl = RCP["glow"] if glow == GLOW else glow
            out.append('Dialogue: 0,%s,%s,G%d,,0,0,0,,{\\an5\\move(%.1f,%.1f,%.1f,%.1f,0,210)'
                       '\\blur%.1f\\bord0\\shad0\\1c%s\\alpha&H%s&\\fad(160,240)}%s'
                       % (ts(t_on), ts(t_end), f, px, py + RCP["rise"] + 1, px, py,
                          max(RCP["gmin"], f * RCP["gk"]), bgr(gl),
                          RCP["ga"][1] if is_acc else RCP["ga"][0], ch))
        # 实字层：按配方的字色/描边/投影
        out.append('Dialogue: 2,%s,%s,G%d,,0,0,0,,{\\an5\\move(%.1f,%.1f,%.1f,%.1f,0,210)'
                   '\\bord%.1f\\shad0\\1c%s\\3c%s\\fad(110,200)}%s'
                   % (ts(t_on), ts(t_end), f, px, py + RCP["rise"], px, py,
                      max(RCP["bmin"], f * RCP["bk"]),
                      bgr(RCP["accent"] if is_acc else RCP["ink"]),
                      bgr(RCP.get("out", DARK)), ch))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--font", default="MV Serif SC")
    ap.add_argument("--scale", type=float, default=1.12,
                    help="字号整体倍率（去掉卡片后要放大 10–15%%）")
    ap.add_argument("--glow", default="", help="固定辉光色 R,G,B；不给则用琥珀")
    ap.add_argument("--shadow-max", dest="shadow_max", type=float, default=0.46,
                    help="柔影最大不透明度（0.46 ≈ 半透明影子）")
    ap.add_argument("--sheet", default="", help='静帧路径模板，如 "images/s%%02d.png"；给了才做自适应')
    ap.add_argument("--recipe", default="02-window-glow", choices=sorted(RECIPES),
                    help="字幕配方（见 references/05b-subtitle-recipes.md）")
    a = ap.parse_args()

    global RCP
    RCP = RECIPES[a.recipe]

    glow = GLOW
    if a.glow:
        glow = tuple(int(v) for v in a.glow.split(","))
    sheet = Sheet(a.sheet) if a.sheet else None

    items = json.load(open(a.lines, encoding="utf-8"))
    sizes = set()
    for it in items:
        fs = int(round(int(it.get("fs", 64)) * a.scale))
        sizes.add(fs)
        for v in (it.get("emph") or {}).values():
            sizes.add(int(round(fs * float(v))))

    out = [head(a.font, sorted(sizes))]
    for it in items:
        emit(out, it, sheet, a.scale, glow, a.shadow_max)
    open(a.out, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print("写入 %s  事件 %d  字号档 %s" % (a.out, len(out) - 1, sorted(sizes)))


if __name__ == "__main__":
    main()
