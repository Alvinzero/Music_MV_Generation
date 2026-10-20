#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成"一字一纸片、逐字蹦出、卡在拍上"的 ASS 字幕。

用法:
    python make_subs.py --lines lines.json --beats beats.json --out subs.ass \
        [--font "ZCOOL KuaiLe"]

lines.json（每句一条）:
    [
      {"start":1.83,"end":4.30,"text":"我们都是渺小真实存在","place":"M"},
      {"start":8.35,"end":10.60,"text":"直到遇见你我以为就光明起来","place":"B"},
      {"start":54.0,"end":56.0,"text":"把回忆拼好给你","title":true}
    ]
    place: T 顶部 / M 中部 / B 底部；title 为整块浮现的片尾标题

要点（都已在实现里）:
  · 颜色按 ASS 的 &HAABBGGRR 写（BGR 倒序）；\\1c \\3c \\4c 用 &HBBGGRR&
  · 每个字独立事件、独立 \\pos、独立 \\frz，纸片 = BorderStyle=3 底框
  · 字的出现时刻吸附到 1/8 拍网格；每句首字就近吸附（不偏向后方）
  · 超过 CHUNK_MAX 字自动均分成前后两段轮流显示
"""

import argparse
import json
import os

import numpy as np

# ---- 版式（手机可读为基准，可按画面调整）----
FS, PAD, GAP, ROW_Y = 84, 22, 12, 1000     # 正文：字号 / 纸边留白 / 片间缝 / 底部行中心
TOP_Y, MID_Y = 96, 420                      # 顶部 / 中部行中心
TFS, TPAD, TGAP, TROW_Y = 120, 26, 16, 878  # 片尾标题
CHUNK_MAX = 12                              # 每段最多几个字
MIN_STEP = 0.15                             # 每字最短间隔，防密集句过快
TILT = [-3.2, 2.1, -1.4, 3.6, -2.4, 1.2, -0.8, 2.9, -3.8, 1.8, -1.9, 3.1]

# 每句一套 (纸片色, 字色, 纸边)，按情绪推进；不够则循环
PALETTE = [
    ((241, 234, 217), (56, 48, 38), (214, 199, 176)),
    ((231, 219, 224), (92, 52, 72), (199, 184, 190)),
    ((247, 234, 216), (122, 74, 32), (212, 192, 165)),
    ((223, 236, 240), (29, 82, 102), (177, 201, 211)),
    ((250, 228, 220), (142, 63, 50), (217, 187, 177)),
    ((212, 216, 221), (36, 38, 44), (174, 179, 186)),
    ((230, 239, 228), (42, 90, 66), (186, 201, 182)),
    ((248, 238, 208), (124, 97, 18), (214, 199, 162)),
    ((237, 227, 241), (86, 50, 126), (197, 183, 205)),
    ((249, 224, 233), (142, 42, 92), (214, 181, 194)),
    ((227, 234, 239), (53, 80, 107), (183, 195, 203)),
    ((247, 226, 219), (142, 48, 37), (214, 183, 175)),
    ((243, 232, 205), (97, 72, 30), (210, 196, 163)),
]


def bgr(rgb):
    r, g, b = rgb
    return "&H%02X%02X%02X&" % (b, g, r)


def bgr_a(rgb, alpha=0x00):
    r, g, b = rgb
    return "&H%02X%02X%02X%02X" % (alpha, b, g, r)


def ts(t):
    return "%d:%02d:%05.2f" % (int(t // 3600), int(t % 3600 // 60), t % 60)


def head(font):
    fill, ink, edge = PALETTE[0]
    return """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Tile,{font},{fs},{ink},{ink},{edge},{fill},-1,0,0,0,100,100,1.8,0,3,{pad},0,5,0,0,0,1
Style: BigTile,{font},{tfs},{tink},{tink},{tedge},{tfill},-1,0,0,0,100,100,3.5,0,3,{tpad},0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(font=font, fs=FS, pad=PAD, tfs=TFS, tpad=TPAD,
           ink=bgr_a(ink), edge=bgr_a(edge), fill=bgr_a(fill),
           tink=bgr_a(PALETTE[12][1]), tedge=bgr_a(PALETTE[12][2]), tfill=bgr_a(PALETTE[12][0]))


class BeatGrid:
    def __init__(self, path):
        self.ok = False
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                b = json.load(f)
            self.base = b["beat_period"] / 8.0
            self.off = b["offset"]
            self.ok = True

    def snap(self, t):
        if not self.ok:
            return t
        return self.off + round((t - self.off) / self.base) * self.base

    def plan(self, start, end, n):
        """把 n 个字排到网格上：步长取网格整数或半整数倍，首字就近吸附。"""
        if not self.ok:
            step = (end - start) / n
            return [start + i * step for i in range(n)]
        base, dur = self.base, end - start
        best_m, best_err = None, 1e18
        m = 0.5
        while m <= 24:
            span = n * m * base
            if span > dur + 0.50:
                break
            if m * base >= MIN_STEP:
                err = abs(span - dur)
                if best_m is None or err < best_err - 1e-9:
                    best_m, best_err = m, err
            m += 0.5
        if best_m is None:
            best_m = max(0.5, np.ceil(MIN_STEP / base * 2) / 2)
        step = best_m * base

        # 首字：在 [start-0.20, start+0.10] 里取最近网格点（正拍仅在 ±0.06 内才用）
        lo, hi = start - 0.20, start + 0.10
        k_lo = int(np.ceil((lo - self.off) / base))
        k_hi = int(np.floor((hi - self.off) / base))
        cands = list(range(k_lo, k_hi + 1))
        if cands:
            strong = [k for k in cands if k % 8 == 0
                      and abs(self.off + k * base - start) <= 0.06]
            pool = strong if strong else cands
            t0 = self.off + min(pool, key=lambda k: abs(self.off + k * base - start)) * base
        else:
            t0 = self.off + np.ceil((start - self.off) / base) * base
        return [t0 + i * step for i in range(n)]


def emit(out, item, grid, idx):
    text = "".join(ch for ch in item["text"] if ch.strip())
    if not text:
        return
    start, end = float(item["start"]), float(item["end"])
    title = bool(item.get("title"))
    place = item.get("place", "B")
    fs, pad, gap, y = (TFS, TPAD, TGAP, TROW_Y) if title else (FS, PAD, GAP, ROW_Y)
    if place == "T" and not title:
        y = TOP_Y
    elif place == "M" and not title:
        y = MID_Y
    tile = fs + 2 * pad

    times = [start] * len(text) if title else grid.plan(start, end, len(text))
    hold = 0.0 if title else 0.30

    n = len(text)
    if title or n <= CHUNK_MAX:
        chunks = [text]
    else:
        k = -(-n // CHUNK_MAX)
        base_len, extra = divmod(n, k)
        chunks, pos = [], 0
        for c in range(k):
            size = base_len + (1 if c < extra else 0)
            chunks.append(text[pos:pos + size])
            pos += size

    i = 0
    for ci, chunk in enumerate(chunks):
        m = len(chunk)
        total = m * tile + (m - 1) * gap
        x0 = (1920 - total) / 2 + tile / 2
        if i + m < n:
            seg_end = times[i + m] + 0.10
        else:
            seg_end = max(end + hold, times[min(i + m - 1, n - 1)] + 0.35)
        for j, ch in enumerate(chunk):
            k = i + j
            t_on = times[k]
            t_end = max(seg_end, t_on + 0.35)
            rot = TILT[k % len(TILT)] * (1.25 if title else 1.0)
            x = x0 + j * (tile + gap)
            if title:
                anim = "\\fscx92\\fscy92\\t(0,320,\\fscx100\\fscy100)\\fad(420,0)"
            else:
                out_ms = 150 if i + m < n else 0
                anim = ("\\fscx50\\fscy50\\t(0,80,\\fscx118\\fscy118)"
                        "\\t(80,170,\\fscx100\\fscy100)\\fad(55,%d)" % out_ms)
            head_txt = ("{\\an5\\pos(%.1f,%.1f)\\frz%.2f%s\\1c%s\\2c&HFF000000&\\3c%s\\4c%s}"
                        % (x, y, rot, anim, bgr(PALETTE[idx][1]),
                           bgr(PALETTE[idx][2]), bgr(PALETTE[idx][0])))
            out.append("Dialogue: 0,%s,%s,%s,,0,0,0,,%s%s"
                       % (ts(t_on), ts(t_end),
                          "BigTile" if title else "Tile", head_txt, ch))
        i += m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", required=True)
    ap.add_argument("--beats", default="")
    ap.add_argument("--out", default="subs.ass")
    ap.add_argument("--font", default="ZCOOL KuaiLe")
    a = ap.parse_args()

    with open(a.lines, encoding="utf-8") as f:
        items = json.load(f)
    grid = BeatGrid(a.beats)

    lines = [head(a.font)]
    allt = []
    for idx, it in enumerate(items):
        emit(lines, it, grid, idx % len(PALETTE))
        txt = "".join(c for c in it["text"] if c.strip())
        if not it.get("title"):
            allt += grid.plan(float(it["start"]), float(it["end"]), len(txt))

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("written:", a.out, "events:", len(lines) - 1)
    if grid.ok:
        errs = [abs(t - grid.snap(t)) for t in allt]
        print("网格 %.4fs 偏移 %.3fs 最大偏离 %.4fs"
              % (grid.base, grid.off, max(errs) if errs else 0))


if __name__ == "__main__":
    main()
