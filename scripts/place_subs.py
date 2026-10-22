#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐句定字幕位置：按画面空档选 y，按字数定字号，输出 make_subs.py 吃的 lines.json。

    python place_subs.py --lines out/lines_aligned.json --shots out/shots.json \
        --images images/c16 -o out/lines.json

不给 --shots 时按时间找最近的帧目录编号；连 --images 都没有就统一压在下沿。

定位原则：**有人的镜头一律压 y=946（可压脚不能压脸）**；
空镜才做"行梯度 + 饱和度"搜索，找最干净的一条带。
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

PAD_R, GAP, MAXW = 0.24, -6, 1800
FS_LIST = [66, 62, 58, 54, 50]
EMPH = set("等想爱再从前永远再见微甜远方月光雪秋风信糖街")

# 需要"字幕融入画面"的句子：序号 → (fs, ink, edge, y)。每分钟约 1 处，宁少勿多。
SCENE = {}


def width_of(n, fs):
    return n * fs * (1 + 2 * PAD_R) + (n - 1) * GAP


def pick_fs(n):
    for fs in FS_LIST:
        if width_of(n, fs) <= MAXW:
            return fs
    return FS_LIST[-1]


_c = {}


def band_energy(img_path):
    if img_path in _c:
        return _c[img_path]
    rgb = np.asarray(Image.open(img_path).convert("RGB"), dtype=np.float32)
    g = np.abs(np.diff(rgb.mean(axis=2), axis=0)).mean(axis=1)
    g = np.convolve(g, np.ones(9) / 9, mode="same")
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    sat = np.convolve(((mx - mn) / (mx + 1e-3)).mean(axis=1), np.ones(21) / 21, mode="same")
    _c[img_path] = (g, sat)
    return g, sat


def band_score(img_path, y, card_h):
    g, sat = band_energy(img_path)
    H = len(g)
    y0, y1 = max(0, int(y - card_h / 2)), min(H - 1, int(y + card_h / 2))
    return 0.55 * float(g[y0:y1].mean()) + 46.0 * float(sat[y0:y1].mean())


def best_y(img_path, card_h, prev=None):
    cands = [946, 892, 838, 784, 724, 664, 560, 460, 360, 260, 180, 130]
    vals = [band_score(img_path, y, card_h) for y in cands]
    lo, hi = min(vals), max(vals)
    norm = [(v - lo) / (hi - lo + 1e-6) for v in vals]
    order = list(range(len(cands)))
    if prev is not None:
        moved = [k for k in order if abs(cands[k] - prev) >= 45]
        order = moved or order
    for k in order:
        if norm[k] < 0.42:
            return cands[k]
    return cands[min(order, key=lambda t: norm[t])]


def image_for(t, shots, images):
    if shots and images:
        for s in shots:
            if s["start"] <= t < s["end"]:
                p = os.path.join(images, "s%02d.png" % s["idx"])
                return p if os.path.exists(p) else None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", required=True, help="align.py 的输出")
    ap.add_argument("--shots", help="shots.json：[{idx,start,end,kind}]")
    ap.add_argument("--images", help="逐镜静帧目录（c16 图）")
    ap.add_argument("-o", "--out", default="out/lines.json")
    a = ap.parse_args()

    lines = json.load(open(a.lines, encoding="utf-8"))
    shots = json.load(open(a.shots, encoding="utf-8")) if a.shots else None

    items = []
    for it in lines:
        text = it["text"]
        cs = [c for c in text if c.strip()]
        ts = list(it.get("times") or [])
        n = len(cs)
        if len(ts) != n:
            ts = list(np.linspace(it["start"], it["end"], n))

        # 按原句空格切段（>12 字）
        sp_after, cnt = set(), 0
        for ch in text:
            if ch.strip():
                cnt += 1
            elif cnt > 0:
                sp_after.add(cnt - 1)
        chunks = [(0, n)]
        if n > 12:
            cand = [k for k in sp_after if 3 <= k <= n - 3]
            k = min(cand, key=lambda x: abs(x - n / 2)) if cand else (n + 1) // 2
            chunks = [(0, k + 1), (k + 1, n)]

        prev_y = None
        for ci, (lo, hi) in enumerate(chunks):
            seg_t = ts[lo:hi]
            seg_text = "".join(cs[lo:hi])
            s = seg_t[0]
            e = ts[hi] if hi < n else it["end"]
            e = max(e, seg_t[-1] + 0.25)
            rec = {"start": round(s, 2), "end": round(e, 2), "text": seg_text,
                   "times": [round(v, 2) for v in seg_t]}
            if ci == 0 and it.get("n") in SCENE:
                fs, ink, edge, y = SCENE[it["n"]]
                rec.update(dict(x=960, y=y, fs=fs, mode="scene",
                                ink=list(ink), edge=list(edge)))
            else:
                fs = pick_fs(len(seg_text))
                img = image_for((s + e) / 2, shots, a.images) if a.images else None
                if img:
                    sh = next((x for x in shots
                               if x["start"] <= (s + e) / 2 < x["end"]), {})
                    if sh.get("kind") in ("both", "boy", "girl"):
                        y = 946 if prev_y is None else (946 if abs(946 - prev_y) >= 45 else 902)
                    else:
                        y = best_y(img, fs * 1.5, prev_y)
                else:
                    y = 946
                prev_y = y
                rec.update(dict(x=960, y=y, fs=fs))
                idxs = [i for i, c in enumerate(seg_text) if c in EMPH]
                rec["accent"] = idxs[0] if idxs else -1
            items.append(rec)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(items, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("字幕条数 %d（带逐字时间 %d） → %s"
          % (len(items), sum(1 for i in items if i.get("times")), a.out))


if __name__ == "__main__":
    main()
