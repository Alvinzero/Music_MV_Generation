#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纸卡逐字字幕（参考风格版）。

风格来源：逐帧拆解参考 MV 后的四条规律
  1. 每个字一张独立纸卡，衬线字，卡片随字轻微旋转、上下错落、彼此叠压
  2. 逐字出现，跟着唱到的字走，左端固定向右生长（不是整行一起淡入）
  3. 首字（或指定的重点字）用珊瑚色卡 + 米色字，其余为米白卡 + 墨色字
  4. 关键的字可以放大——一句里允许字号不统一，用来做重音

lines.json 每项：
  {"start":15.0,"end":18.0,"text":"你住的巷子里","x":800,"y":1005,"fs":66,
   "accent":0,"emph":{"4":1.35}}
  x/y = 整行（长成之后）的中心点；accent 为高亮字下标，-1 关闭；emph 为字下标→放大倍数
"""

import argparse
import json
import os

import numpy as np

FS = 66
PAD_R = 0.24          # 纸边 = fs * PAD_R
GAP = -6              # 负值让纸卡轻微叠压
CHUNK_MAX = 12
MIN_STEP = 0.15
SAFE_X = 26

PAPER = (242, 230, 206)
INK = (74, 66, 68)
SHADOW = (150, 138, 126)
CORAL = (231, 170, 156)
CORAL_INK = (251, 245, 236)

# 固定种子的抖动，保证每次渲染一致
def jit(i, amp, seed=0):
    x = (i * 2654435761 + seed * 40503) & 0xFFFFFFFF
    x ^= x >> 13
    return ((x % 2001) / 1000.0 - 1.0) * amp


def bgr(rgb):
    r, g, b = rgb
    return "&H%02X%02X%02X&" % (b, g, r)


def bgr_a(rgb, alpha=0x00):
    r, g, b = rgb
    return "&H%02X%02X%02X%02X" % (alpha, b, g, r)


def ts(t):
    return "%d:%02d:%05.2f" % (int(t // 3600), int(t % 3600 // 60), t % 60)


def pad_of(fs):
    return max(8, int(round(fs * PAD_R)))


def head(font, sizes):
    st = []
    for fs in sizes:
        st.append("Style: C%d,%s,%d,%s,%s,%s,%s,0,0,0,0,100,100,0.5,0,3,%d,4,5,0,0,0,1"
                  % (fs, font, fs, bgr_a(INK), bgr_a(INK), bgr_a(PAPER), bgr_a(SHADOW), pad_of(fs)))
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


class BeatGrid:
    def __init__(self, path):
        self.ok = False
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                b = json.load(f)
            self.base = b["beat_period"] / 8.0
            self.off = b["offset"]
            self.ok = True

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


def emit(out, item, grid):
    text = "".join(c for c in item["text"] if c.strip())
    if not text:
        return
    start, end = float(item["start"]), float(item["end"])
    is_title = bool(item.get("title"))
    fs0 = int(item.get("fs", 120 if is_title else FS))
    cx = float(item.get("x", 960))
    if "y" in item:
        cy = float(item["y"])
    else:                                   # 兜底：老写法 place T/M/B
        cy = {"T": 96, "M": 420}.get(item.get("place", "B"), 1000)
    accent = -1 if is_title else int(item.get("accent", 0))
    emph = {int(k): float(v) for k, v in (item.get("emph") or {}).items()}

    # 题字整块快速浮出，不跟着唱词慢慢铺
    times = ([start + i * 0.10 for i in range(len(text))]
             if is_title else grid.plan(start, end, len(text)))

    n = len(text)
    if n <= CHUNK_MAX:
        chunks = [(0, text)]
    else:
        k = -(-n // CHUNK_MAX)
        base_len, extra = divmod(n, k)
        chunks, pos = [], 0
        for c in range(k):
            size = base_len + (1 if c < extra else 0)
            chunks.append((pos, text[pos:pos + size]))
            pos += size

    for cstart, chunk in chunks:
        # 先算这一段的最终总宽，把左端定在"长成之后仍居中"的位置
        widths = []
        for j, ch in enumerate(chunk):
            s = emph.get(cstart + j, 1.0)
            fs = int(round(fs0 * s))
            widths.append((fs, fs + 2 * pad_of(fs)))
        total = sum(w for _, w in widths) + (len(chunk) - 1) * GAP
        left = min(max(cx - total / 2, SAFE_X), 1920 - SAFE_X - total)

        cur = left
        seg_end = times[cstart + len(chunk)] if cstart + len(chunk) < n else end + 0.28
        for j, ch in enumerate(chunk):
            fs, tile = widths[j]
            idx = cstart + j
            t_on = times[idx]
            t_end = max(seg_end, t_on + 0.35)
            rot = jit(idx, 2.8, 7)
            dy = jit(idx, 6.0, 19)
            x = cur + tile / 2
            cur += tile + GAP

            is_accent = (idx == accent)
            fill, ink = (CORAL, CORAL_INK) if is_accent else (PAPER, INK)
            anim = "\\fscx88\\fscy88\\t(0,80,\\fscx100\\fscy100)\\fad(36,120)"
            out.append("Dialogue: 0,%s,%s,C%d,,0,0,0,,"
                       "{\\an5\\pos(%.1f,%.1f)\\frz%.2f%s\\1c%s\\2c&HFF000000&\\3c%s\\4c%s}%s"
                       % (ts(t_on), ts(t_end), fs, x, cy + dy, rot, anim,
                          bgr(ink), bgr(fill), bgr(SHADOW), ch))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", required=True)
    ap.add_argument("--beats", default="")
    ap.add_argument("--out", default="subs.ass")
    ap.add_argument("--font", default="MV Serif SC")
    a = ap.parse_args()

    with open(a.lines, encoding="utf-8") as f:
        items = json.load(f)
    grid = BeatGrid(a.beats)

    sizes = set()
    for it in items:
        fs0 = int(it.get("fs", 120 if it.get("title") else FS))
        emph = {int(k): float(v) for k, v in (it.get("emph") or {}).items()}
        sizes.add(fs0)
        for v in emph.values():
            sizes.add(int(round(fs0 * v)))
    lines = [head(a.font, sorted(sizes))]

    for it in items:
        emit(lines, it, grid)

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("written:", a.out, "events:", len(lines) - 1, "sizes:", sorted(sizes))


if __name__ == "__main__":
    main()
