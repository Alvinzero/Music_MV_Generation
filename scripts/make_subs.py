#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐句可定位的纸片字幕生成器。

核心：字幕位置不是"顶/中/底"三档，而是**每句一个中心点 + 一个字号**。
      排布方法见 references/subtitle-layout.md。

  · 每句可给 "x" / "y" / "fs"，按该镜头的实际空档摆位
  · 纸边(pad)、字缝(gap) 随字号等比缩放，缩字号时不会出现"大框小字"
  · 越界自动回拉，保证整行不出画
  · 超 12 字自动均分成前后两段，避免一行顶满画面

lines.json 每项：
  {"start":15.0,"end":18.0,"text":"你住的巷子里","x":800,"y":1005,"fs":80}
  x/y 为整行的中心点；省略则退回 place(T/M/B) 与默认字号。

用法:
  python make_subs.py --lines out/lines.json --beats out/beats.json \
      --font "ZCOOL KuaiLe" --out out/subs.ass
"""

import argparse
import json
import os

import numpy as np

# ---- 版式 ----
FS, ROW_Y = 84, 1000
TOP_Y, MID_Y = 96, 420
TFS, TROW_Y = 120, 878
CHUNK_MAX = 12
MIN_STEP = 0.15
SAFE_X = 30          # 左右安全边
TILT = [-3.2, 2.1, -1.4, 3.6, -2.4, 1.2, -0.8, 2.9, -3.8, 1.8, -1.9, 3.1]

# 每句一套 (投影色, 字色, 纸面色)，纸雕色盘
PALETTE = [
    ((226, 216, 198), (56, 48, 38), (246, 240, 228)),
    ((196, 183, 164), (36, 48, 70), (232, 224, 208)),
    ((186, 199, 220), (26, 48, 96), (224, 234, 248)),
    ((214, 186, 158), (92, 56, 28), (238, 220, 198)),
    ((176, 190, 232), (30, 50, 140), (226, 234, 252)),
    ((206, 206, 202), (40, 44, 52), (238, 238, 234)),
]
TITLE_IDX = 5


def metrics(fs):
    """按字号推出纸边与字缝，保持视觉比例。"""
    pad = max(9, int(round(fs * 0.26 / 2) * 2))
    gap = max(6, int(round(fs * 0.13)))
    return fs, pad, gap, fs + 2 * pad


def bgr(rgb):
    r, g, b = rgb
    return "&H%02X%02X%02X&" % (b, g, r)


def bgr_a(rgb, alpha=0x00):
    r, g, b = rgb
    return "&H%02X%02X%02X%02X" % (alpha, b, g, r)


def ts(t):
    return "%d:%02d:%05.2f" % (int(t // 3600), int(t % 3600 // 60), t % 60)


def head(font, sizes):
    fill, ink, edge = PALETTE[0]
    dyn = []
    for fs in sizes:
        pad = metrics(fs)[1]
        dyn.append("Style: T%d,%s,%d,%s,%s,%s,%s,-1,0,0,0,100,100,1.8,0,3,%d,0,5,0,0,0,1"
                   % (fs, font, fs, bgr_a(ink), bgr_a(ink), bgr_a(edge), bgr_a(fill), pad))
    return """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}
Style: BigTile,{font},{tfs},{tink},{tink},{tedge},{tfill},-1,0,0,0,100,100,3.5,0,3,{tpad},0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(font=font, styles="\n".join(dyn), tfs=TFS, tpad=metrics(TFS)[1],
           tink=bgr_a(PALETTE[TITLE_IDX][1]), tedge=bgr_a(PALETTE[TITLE_IDX][2]),
           tfill=bgr_a(PALETTE[TITLE_IDX][0]))


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

    fs = int(item.get("fs", TFS if title else FS))
    fs, pad, gap, tile = metrics(fs)

    # 位置：显式 x/y 优先，否则退回 place
    place = item.get("place", "B")
    cy = float(item.get("y", TROW_Y if title else ROW_Y))
    if "y" not in item:
        if place == "T":
            cy = TOP_Y
        elif place == "M":
            cy = MID_Y
    cx = float(item.get("x", 960))

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
    for chunk in chunks:
        m = len(chunk)
        total = m * tile + (m - 1) * gap
        # 越界回拉
        cx_use = min(max(cx, SAFE_X + total / 2), 1920 - SAFE_X - total / 2)
        x0 = cx_use - total / 2 + tile / 2
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
                        % (x, cy, rot, anim, bgr(PALETTE[idx][1]),
                           bgr(PALETTE[idx][2]), bgr(PALETTE[idx][0])))
            out.append("Dialogue: 0,%s,%s,%s,,0,0,0,,%s%s"
                       % (ts(t_on), ts(t_end),
                          "BigTile" if title else "T%d" % fs, head_txt, ch))
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

    sizes = sorted({int(it.get("fs", TFS if it.get("title") else FS)) for it in items
                    if not it.get("title")})
    lines = [head(a.font, sizes)]
    allt, wide = [], []
    for idx, it in enumerate(items):
        emit(lines, it, grid, idx % len(PALETTE))
        txt = "".join(c for c in it["text"] if c.strip())
        if not it.get("title"):
            allt += grid.plan(float(it["start"]), float(it["end"]), len(txt))
            fs = int(it.get("fs", FS))
            _, pad, gap, tile = metrics(fs)
            n = len(txt)
            chunks = 1 if n <= CHUNK_MAX else -(-n // CHUNK_MAX)
            per = -(-n // chunks)
            w = per * tile + (per - 1) * gap
            if w > 1860:
                wide.append((it["text"][:8], w))

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("written:", a.out, "events:", len(lines) - 1)
    if grid.ok:
        errs = [abs(t - grid.snap(t)) for t in allt]
        print("网格 %.4fs 偏移 %.3fs 最大偏离 %.4fs"
              % (grid.base, grid.off, max(errs) if errs else 0))
    print("超宽行:", wide or "无")


if __name__ == "__main__":
    main()
