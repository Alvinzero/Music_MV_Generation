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


def head(font, sizes, scene_sizes=(), carrier_sizes=()):
    st = []
    for fs in sizes:
        st.append("Style: C%d,%s,%d,%s,%s,%s,%s,0,0,0,0,100,100,0.5,0,3,%d,4,5,0,0,0,1"
                  % (fs, font, fs, bgr_a(INK), bgr_a(INK), bgr_a(PAPER), bgr_a(SHADOW), pad_of(fs)))
    for fs in scene_sizes:
        # BorderStyle=1：描边 + 投影，没有纸卡；描边色由事件里的 c 决定
        st.append("Style: S%d,%s,%d,%s,%s,%s,%s,0,0,0,0,100,100,3,0,1,%d,5,5,0,0,0,1"
                  % (fs, font, fs, bgr_a(INK), bgr_a(INK), bgr_a(PAPER), bgr_a(SHADOW),
                     max(6, int(round(fs * 0.07)))))
    for fs in carrier_sizes:
        # 载体模式：字没有纸卡，只留字本身，底托由矢量形状画
        st.append("Style: B%d,%s,%d,%s,%s,%s,%s,0,0,0,0,100,100,0.5,0,1,0,0,5,0,0,0,1"
                  % (fs, font, fs, bgr_a(INK), bgr_a(INK), bgr_a(PAPER), bgr_a(SHADOW)))
    # 矢量形状（纸卡/气球底托），颜色由事件覆盖
    st.append("Style: Shape,%s,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
              "0,0,0,0,100,100,0,0,1,2,0,7,0,0,0,1" % font)
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


def carrier_path(kind, fs):
    """返回 dict(body, string, hilite, w, h, cy)。坐标以 0,0 为左上。"""
    if kind == "balloon":
        w = fs * 1.62
        h = fs * 2.52
        cx, cy = w / 2, h * 0.315
        rx, ry = w * 0.435, h * 0.300
        k = 0.5523
        body = ("m %.1f %.1f b %.1f %.1f %.1f %.1f %.1f %.1f "
                "b %.1f %.1f %.1f %.1f %.1f %.1f "
                "b %.1f %.1f %.1f %.1f %.1f %.1f "
                "b %.1f %.1f %.1f %.1f %.1f %.1f" % (
                    cx, cy - ry,
                    cx + rx * k, cy - ry, cx + rx, cy - ry * k, cx + rx, cy,
                    cx + rx, cy + ry * k, cx + rx * k, cy + ry, cx, cy + ry,
                    cx - rx * k, cy + ry, cx - rx, cy + ry * k, cx - rx, cy,
                    cx - rx, cy - ry * k, cx - rx * k, cy - ry, cx, cy - ry))
        # 气嘴
        ky = cy + ry * 0.93
        body += (" m %.1f %.1f l %.1f %.1f l %.1f %.1f l %.1f %.1f" % (
            cx - fs * 0.062, ky, cx + fs * 0.062, ky,
            cx, ky + fs * 0.105, cx - fs * 0.062, ky))
        # 高光：左上角一枚小椭圆（用局部坐标，外框从 0,0 起）
        hrx, hry = rx * 0.21, ry * 0.18
        hil = ("m %.1f %.1f b %.1f %.1f %.1f %.1f %.1f %.1f "
               "b %.1f %.1f %.1f %.1f %.1f %.1f "
               "b %.1f %.1f %.1f %.1f %.1f %.1f "
               "b %.1f %.1f %.1f %.1f %.1f %.1f" % (
                   hrx, 0,
                   hrx + hrx * k, 0, hrx * 2, hry - hry * k, hrx * 2, hry,
                   hrx * 2, hry + hry * k, hrx + hrx * k, hry * 2, hrx, hry * 2,
                   hrx - hrx * k, hry * 2, 0, hry + hry * k, 0, hry,
                   0, hry - hry * k, hrx - hrx * k, 0, hrx, 0))
        hil_off = (cx - rx * 0.42 - hrx, cy - ry * 0.40 - hry)
        # 细绳：两段折线，带一点弧度感
        ty = ky + fs * 0.10
        string = ("m %.1f %.1f l %.1f %.1f l %.1f %.1f l %.1f %.1f "
                  "l %.1f %.1f l %.1f %.1f" % (
                      cx - 0.7, ty, cx + 0.7, ty, cx + 0.7, h * 0.72,
                      cx + 2.0, h * 0.86, cx + 2.0, h * 0.995, cx + 0.6, h * 0.995))
        return dict(body=body, string=string, hilite=hil, hil_off=hil_off), w, h, cy
    if kind == "puzzle":
        w = h = fs * 1.22
        q = fs * 0.13
        path = ("m %.1f %.1f l %.1f %.1f l %.1f 0 l %.1f %.1f "
                "l %.1f 0 l %.1f %.1f l %.1f %.1f l %.1f %.1f "
                "l %.1f %.1f l %.1f %.1f l %.1f %.1f l %.1f %.1f z") % (
            q, 0, w * 0.5 - q, 0, w * 0.5 - q, -q,
            w * 0.5 + q, -q, w * 0.5 + q, 0, w - q, 0,
            w, q, w, h - q, w - q, h,
            w * 0.5 + q, h, w * 0.5 - q, h, q, h)
        return dict(body=path, string="", hilite="", hil_off=(0, 0)), w, h, h / 2
    return dict(body="", string="", hilite="", hil_off=(0, 0)), 0, 0, 0


def emit(out, item, grid):
    text = "".join(c for c in item["text"] if c.strip())
    if not text:
        return
    start, end = float(item["start"]), float(item["end"])
    disp_end = float(item.get("hold_end", end))   # 只延长显示，不改逐字节奏
    is_title = bool(item.get("title"))
    fs0 = int(item.get("fs", 120 if is_title else FS))
    cx = float(item.get("x", 960))
    if "y" in item:
        cy = float(item["y"])
    else:                                   # 兜底：老写法 place T/M/B
        cy = {"T": 96, "M": 420}.get(item.get("place", "B"), 1000)
    accent = -1 if is_title else int(item.get("accent", 0))
    scene = item.get("mode") == "scene"
    carrier = item.get("carrier")
    mv_ok = bool(item.get("move"))
    tints = item.get("tints") or []

    def tint_of(i):
        for t in tints:
            if t.get("from", 0) <= i <= t.get("to", 10 ** 6):
                return t
        return None
    emph = {int(k): float(v) for k, v in (item.get("emph") or {}).items()}

    # 题字整块快速浮出，不跟着唱词慢慢铺
    times = ([start + i * 0.10 for i in range(len(text))]
             if is_title else grid.plan(start, end, len(text)))

    n = len(text)
    # 场景联动整句一行铺开，不拆段——大字一拆就会跳位
    if scene or n <= CHUNK_MAX:
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
            # 场景模式没有纸卡，字宽按字号走
            widths.append((fs, int(round(fs * 1.06)) if scene else
                            (int(round(fs * 1.74)) if carrier else fs + 2 * pad_of(fs))))
        total = sum(w for _, w in widths) + (len(chunk) - 1) * GAP
        left = min(max(cx - total / 2, SAFE_X), 1920 - SAFE_X - total)

        cur = left
        seg_end = (times[cstart + len(chunk)] if cstart + len(chunk) < n
                   else disp_end + 0.28)
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
            if scene:
                ink = item.get("ink", (228, 213, 196))
                edge = item.get("edge", (10, 43, 82))
                style = "S%d" % fs
                anim = "\\fad(90,160)"
            else:
                t = tint_of(idx)
                if t:
                    edge, ink = tuple(t.get("paper", PAPER)), tuple(t.get("ink", INK))
                else:
                    edge, ink = (CORAL, CORAL_INK) if is_accent else (PAPER, INK)
                style = ("B%d" % fs) if carrier else ("C%d" % fs)
                anim = "\\fscx88\\fscy88\\t(0,80,\\fscx100\\fscy100)\\fad(36,120)"

            # ---- 动作层：位移轨迹 ----
            yc = cy + dy
            only = item.get("move_i")
            mv = item.get("move") if (mv_ok and (not only or idx in only)) else None
            if mv:
                d0 = mv.get("d0", [0, 0])
                d1 = mv.get("d1", [0, 0])
                sway = float(mv.get("sway", 0)) * (idx - (n - 1) / 2)
                dur = int(mv.get("dur") or max(300, (t_end - t_on) * 1000))
                x1, y1 = x + d0[0] + sway * 0.35, yc + d0[1]
                x2, y2 = x + d1[0] + sway, yc + d1[1]
                r0 = mv.get("frz0", rot)
                r1 = mv.get("frz1", rot)
                pos_s = "\\move(%.1f,%.1f,%.1f,%.1f,0,%d)" % (x1, y1, x2, y2, dur)
                rot_s = "\\frz%.2f\\t(0,%d,\\frz%.2f)" % (r0, dur, r1)
                sc = float(mv.get("scale") or 0)
                if sc:
                    rot_s += "\\t(0,%d,\\fscx%d\\fscy%d)" % (dur, int(sc * 100), int(sc * 100))
                fin, fout = mv.get("fade", [260, 220])
                anim = "%s\\fad(%d,%d)" % (rot_s, fin, fout)
                anchor = (x1, y1)
                mv_box = (x1, y1, x2, y2, dur)
            else:
                pos_s = "\\pos(%.1f,%.1f)" % (x, yc)
                anchor = (x, yc)
                rot_s = "\\frz%.2f" % rot
                mv_box = None

            # ---- 载体层：异形底托 ----
            if carrier and not scene:
                paths, cw, chh, cay = carrier_path(carrier, fs)
                path = paths["body"]
                if path:
                    fills = item.get("carrier_fills") or [item.get("carrier_fill", (232, 156, 138))]
                    cfill = tuple(fills[idx % len(fills)])
                    cline = item.get("carrier_line", (150, 86, 70))
                    lum = 0.299 * cfill[0] + 0.587 * cfill[1] + 0.114 * cfill[2]
                    ink = item.get("glyph_ink") or ((74, 66, 68) if lum > 200 else (251, 245, 236))
                    if mv_box:
                        pos_shape = "\\move(%.1f,%.1f,%.1f,%.1f,0,%d)" % (
                            mv_box[0] - cw / 2, mv_box[1] - cay,
                            mv_box[2] - cw / 2, mv_box[3] - cay, mv_box[4])
                    else:
                        pos_shape = "\\pos(%.1f,%.1f)" % (anchor[0] - cw / 2, anchor[1] - cay)
                    out.append(
                        "Dialogue: 0,%s,%s,Shape,,0,0,0,,"
                        "{\\an7%s\\p1\\bord2\\shad0\\1c%s\\3c%s}"
                        "%s{\\p0}"
                        % (ts(t_on), ts(t_end), pos_shape, bgr(cfill), bgr(cline), path))
                    string = paths["string"]
                    if string:
                        out.append(
                            "Dialogue: 0,%s,%s,Shape,,0,0,0,,"
                            "{\an7%s\p1\bord0\shad0\1c%s\3c%s}%s{\p0}"
                            % (ts(t_on), ts(t_end), pos_shape,
                               bgr(item.get("string_color", (146, 118, 100))),
                               bgr(item.get("string_color", (146, 118, 100))), string))

            out.append("Dialogue: 1,%s,%s,%s,,0,0,0,,"
                       "{\\an5%s%s\\1c%s\\2c&HFF000000&\\3c%s\\4c%s}%s"
                       % (ts(t_on), ts(t_end), style, pos_s, anim,
                          bgr(ink), bgr(edge), bgr(edge), ch))


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

    sizes, scene_sizes, carrier_sizes = set(), set(), set()
    for it in items:
        if it.get("mode") == "scene":
            scene_sizes.add(int(it.get("fs", FS)))
            continue
        if it.get("carrier"):
            carrier_sizes.add(int(it.get("fs", FS)))
        fs0 = int(it.get("fs", 120 if it.get("title") else FS))
        emph = {int(k): float(v) for k, v in (it.get("emph") or {}).items()}
        sizes.add(fs0)
        for v in emph.values():
            sizes.add(int(round(fs0 * v)))
    lines = [head(a.font, sorted(sizes), sorted(scene_sizes), sorted(carrier_sizes))]

    for it in items:
        emit(lines, it, grid)

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("written:", a.out, "events:", len(lines) - 1, "sizes:", sorted(sizes))


if __name__ == "__main__":
    main()
