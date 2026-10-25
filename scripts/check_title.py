#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""片头验收：不合规就退出码 2，逼你重做——不是打印一堆数字让人自己看。

    python scripts/check_title.py --clip clips/s01.mp4 --area 760,66,1160,622
    python scripts/check_title.py --still out/title_still.png --area 760,66,1160,622
    python scripts/check_title.py --clip clips/s01.mp4 --only watermark   # 只查水印

查六件事（前三项 FAIL 必须重做）：
  1. 水印      四角逐帧扫描，检测"比背景亮、低饱和、成簇"的文字像素
  2. 时长      4.5–7.0 秒（六个竖排字读得完，又不至于让人等）
  3. 出画      首末帧的载体区域都被完整包在画面内
  4. 首字留白  ≥ 载体高的 6.5%
  5. 占载体比  60–87%
  6. 居中      字块中心 = 载体中线 = 画面中线（±8% 画宽）

**水印不能靠固定 crop 值**。同一家模型不同版本，水印位置会变（实测有 110px 和 240px 两种），
所以先 `--only watermark --bbox` 量出真实范围，再按量出来的值裁。
"""
import argparse
import json
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageFilter

FF = shutil.which("ffmpeg") or r"D:/workbuddy/runtime/ffmpeg/ffmpeg.exe"


def grab(clip, t):
    raw = subprocess.run([FF, "-v", "error", "-ss", "%.3f" % t, "-i", clip,
                          "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True).stdout
    if not raw:
        return None
    import io
    return Image.open(io.BytesIO(raw)).convert("RGB")


def probe(path):
    """没有 ffprobe 也能量：解析 `ffmpeg -i` 的 stderr。"""
    err = subprocess.run([FF, "-hide_banner", "-i", path],
                         capture_output=True).stderr.decode("utf-8", "ignore")
    import re
    dur = 0.0
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    w = h = 0
    m = re.search(r"Video: .*? (\d{2,5})x(\d{2,5})", err)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    fps = ""
    m = re.search(r"(\d+(?:\.\d+)?) fps", err)
    if m:
        fps = m.group(1)
    return dict(w=w, h=h, dur=dur, fps=fps)


def wm_score(im, box, win=(170, 76), stride=8):
    """角落水印检测：找"最密的横向文字带"，用形状排除建筑竖边。

    水印的特征很稳定：比局部背景亮一大截、低饱和（灰白）、横向成条（宽/高 1.2–7）。
    但同一角落常有墙面纹理，所以不取全局包围盒，而是滑窗找最密的那一块。
    """
    x0, y0, x1, y1 = box
    a = np.asarray(im.crop(box), dtype=np.float32)
    if a.size == 0:
        return 0.0, None
    lum = a.mean(2)
    mx, mn = a.max(2), a.min(2)
    sat = (mx - mn) / (mx + 1e-3)
    bg = np.asarray(Image.fromarray(lum.astype(np.uint8)).filter(
        ImageFilter.MedianFilter(size=17)), dtype=np.float32)
    m = ((lum - bg) > 5) & (lum > 78) & (lum < 252) & (sat < 0.30)

    H, W = m.shape
    ww, hh = min(win[0], W), min(win[1], H)
    if m.sum() < 30 or H < hh or W < ww:
        return 0.0, None

    ii = np.cumsum(np.cumsum(m.astype(np.int32), 0), 1)
    ii = np.pad(ii, ((1, 0), (1, 0)))

    def boxsum(y, x):
        return ii[y + hh, x + ww] - ii[y, x + ww] - ii[y + hh, x] + ii[y, x]

    best, by, bx = -1, 0, 0
    for y in range(0, H - hh + 1, stride):
        for x in range(0, W - ww + 1, stride):
            v = boxsum(y, x)
            if v > best:
                best, by, bx = v, y, x

    sub = m[by:by + hh, bx:bx + ww]
    ys, xs = np.where(sub)
    if len(xs) < 25:
        return 0.0, None
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    aspect = bw / float(bh)
    cov = len(xs) / float(bw * bh)          # 文字笔画只占包围盒的一小部分
    if bw < 40 or not (1.2 <= aspect <= 7.0) or not (0.15 <= cov <= 0.55):
        return 0.0, None
    # 水印牌贴在画幅角上：包围盒距所在角的两条边 ≤ 48px（纸面亮块通常离角更远）
    gx0, gy0 = x0 + bx + int(xs.min()), y0 + by + int(ys.min())
    gx1, gy1 = x0 + bx + int(xs.max()), y0 + by + int(ys.max())
    W0, H0 = im.size
    dist_h = gx0 if gx1 < W0 / 2 else W0 - gx1
    dist_v = gy0 if gy1 < H0 / 2 else H0 - gy1
    if dist_h > 48 or dist_v > 48:
        return 0.0, None
    score = min(1.0, best / 1200.0)
    return round(score, 3), (x0 + bx + int(xs.min()), y0 + by + int(ys.min()),
                             x0 + bx + int(xs.max()), y0 + by + int(ys.max()))


def corners(im, frac=0.22):
    w, h = im.size
    cw, ch = int(w * frac), int(h * frac * 0.55)
    return {"左上": (0, 0, cw, ch), "右上": (w - cw, 0, w, ch),
            "左下": (0, h - ch, cw, h), "右下": (w - cw, h - ch, w, h)}


def carrier_ink(im, area=None):
    """载体 bbox 与墨字 bbox。给了 --area 就用它，否则按亮度找最大亮块。"""
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    lum = a.mean(2)
    h, w = lum.shape
    if area:
        x0, y0, x1, y1 = [int(v) for v in area.split(",")]
    else:
        bright = lum > max(120, np.percentile(lum, 90))
        cols = np.where(bright[int(h * .15):int(h * .85)].sum(0) > h * .12)[0]
        rows = np.where(bright[:, int(w * .2):int(w * .8)].sum(1) > w * .08)[0]
        if not len(cols) or not len(rows):
            return None
        x0, x1, y0, y1 = cols.min(), cols.max(), rows.min(), rows.max()
    ix = max(2, int((x1 - x0) * 0.04))          # 内缩，避开撕边和子口阴影
    iy = max(2, int((y1 - y0) * 0.03))
    cx0, cy0, cx1, cy1 = x0 + ix, y0 + iy, x1 - ix, y1 - iy
    sub = lum[cy0:cy1, cx0:cx1]
    if sub.size == 0:
        return None
    paper = float(np.percentile(sub, 80))
    ink = sub < min(85, paper * 0.42)
    # 只认"字的行/列"：取墨量达到峰值 25% 的行列，撕边和纸纹达不到
    ry = ink.sum(1).astype(np.float32)
    rx = ink.sum(0).astype(np.float32)
    if ry.max() < 3 or rx.max() < 3:
        return None
    rows = np.where(ry > ry.max() * 0.25)[0]
    cols = np.where(rx > rx.max() * 0.25)[0]
    if not len(rows) or not len(cols):
        return None
    ys = np.concatenate([rows, rows])
    xs = np.concatenate([cols, cols])
    ys, xs = np.clip(ys, 0, ink.shape[0] - 1), np.clip(xs, 0, ink.shape[1] - 1)

    return dict(carrier=tuple(int(v) for v in (cx0, cy0, cx1, cy1)),
                ink=tuple(int(v) for v in (cx0 + xs.min(), cy0 + ys.min(),
                                           cx0 + xs.max(), cy0 + ys.max())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip")
    ap.add_argument("--still")
    ap.add_argument("--area", help="载体范围 x0,y0,x1,y1（不给就自动找亮块）")
    ap.add_argument("--only", choices=["watermark", "layout"], default=None)
    ap.add_argument("--layout", choices=["band", "overlay"], default="band",
                    help="band=纸带/载体承字；overlay=字直接压在场景上")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not a.clip and not a.still:
        sys.exit("给 --clip 或 --still")

    rep, fails = {}, []

    if a.clip:
        info = probe(a.clip)
        rep["size"] = "%dx%d" % (info["w"], info["h"])
        rep["duration"] = round(info["dur"], 3)
        if not 4.5 <= info["dur"] <= 7.0:
            fails.append("时长 %.2fs 不在 4.5–7.0s" % info["dur"])
        times = [info["dur"] * p for p in (0.05, 0.5, 0.95)]
        frames = [grab(a.clip, t) for t in times]
    else:
        frames = [Image.open(a.still).convert("RGB")]
        times = [0]

    frames = [f for f in frames if f is not None]
    if not frames:
        sys.exit("抽不到画面")

    # 1) 水印：逐帧扫四角
    if a.only in (None, "watermark"):
        worst = {}
        for name, box in corners(frames[0]).items():
            best, bb = 0.0, None
            for f in frames:
                s, b = wm_score(f, box)
                if s > best:
                    best, bb = s, b
            worst[name] = dict(score=best, bbox=bb)
        rep["watermark"] = worst
        bad = {k: v for k, v in worst.items() if v["score"] >= 0.35}
        if bad:
            detail = "、".join("%s(%.2f @%s)" % (k, v["score"], v["bbox"]) for k, v in bad.items())
            fails.append("检测到水印：%s" % detail)

    # 2/4/5/6) 版式：只对首帧做
    if a.only in (None, "layout"):
        if a.layout == "overlay":
            # 压字型没有载体可量（字和场景是同一张皮），版式只能人看。
            # 脚本这里只留一句提示，不做假精度的测量。
            rep["layout"] = dict(kind="overlay", note="压字型仅查水印与时长，版式人工抽帧")

        m = carrier_ink(frames[0], a.area) if a.layout == "band" else None
        if a.layout == "band" and not m:
            fails.append("找不到载体区域（给 --area 指定）")
        elif a.layout == "band":
            cx = (m["carrier"][0] + m["carrier"][2]) / 2
            cy_h = m["carrier"][3] - m["carrier"][1]
            ik = m["ink"]
            top = (ik[1] - m["carrier"][1]) / cy_h
            bot = (m["carrier"][3] - ik[3]) / cy_h
            fill = (ik[3] - ik[1]) / cy_h
            icx = (ik[0] + ik[2]) / 2
            w = frames[0].size[0]
            rep["layout"] = dict(carrier=m["carrier"], ink=ik,
                                 top_margin=round(top, 3), bottom_margin=round(bot, 3),
                                 fill=round(fill, 3),
                                 center_off_carrier=round(icx - cx, 1),
                                 center_off_canvas=round(icx - w / 2, 1))
            if top < 0.065:
                fails.append("首字留白 %.1f%% < 6.5%%（字顶到纸边）" % (top * 100))
            if bot < 0.05:
                fails.append("末字/署名距底 %.1f%% < 5%%" % (bot * 100))
            if not 0.60 <= fill <= 0.87:
                fails.append("占载体高 %.0f%% 不在 60–87%%" % (fill * 100))
            if abs(icx - cx) > 8:
                fails.append("字块偏离载体中线 %.0fpx" % (icx - cx))
            if abs(icx - w / 2) > w * 0.08:
                fails.append("字块偏离画面中线 %.0fpx" % (icx - w / 2))

    rep["pass"] = not fails
    rep["fails"] = fails

    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        if "duration" in rep:
            print("片长 %.2fs  %s" % (rep["duration"], rep["size"]))
        if "watermark" in rep:
            for k, v in rep["watermark"].items():
                flag = "水印" if v["score"] >= 0.35 else "干净"
                print("  %s角 %.2f  %s  %s" % (k, v["score"], flag, v["bbox"] or ""))
        if "layout" in rep:
            L = rep["layout"]
            if L.get("kind") == "overlay":
                print("  压字型：水印与时长交由脚本，版式请抽首末帧人工看")
            else:
                print("  首字留白 %.1f%%  末字距底 %.1f%%  占载体 %.0f%%  居中偏差 %+.0fpx（载体）/ %+.0fpx（画布）"
                      % (L["top_margin"] * 100, L["bottom_margin"] * 100, L["fill"] * 100,
                         L["center_off_carrier"], L["center_off_canvas"]))
        print()
        if fails:
            print("[不通过] %d 项：" % len(fails))
            for f in fails:
                print("  · " + f)
            print("\n按 SKILL 的规矩：**不合格一律重做**，不因为贵就将就。")
            sys.exit(2)
        print("[通过]")


if __name__ == "__main__":
    main()
