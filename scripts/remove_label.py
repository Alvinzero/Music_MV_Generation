#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""去掉网关打在右下角的「AI生成 / WORKBUDDY」标。

和 `crop_watermark.py` 的分工：那个是给内置 VideoGen 的老水印用的（对称裁、保构图）；
这个是给第三方网关的新标用的——**贴右下角、不大、但画面上/视频里都会带**，
所以策略是「先量上边界，只裁底部一条，再用 cover 缩放铺回原尺寸」，不做左右对称裁。

为什么不用固定百分比：这个标是**固定像素尺寸**的图章（约 110×52），
在 1024 宽的图上是 10.7%，在 1920 宽的视频上只有 5.7%；
而视频流的标又被放大过（1344 宽时约 167×75，占高 9.8%）。
写死「裁底部 7%」会在视频上留半截字，务必先量。

用法：
    python remove_label.py --input shot.png --output shot-clean.png
    python remove_label.py --input clip.mp4 --output clip-clean.mp4 --keep-size
    python remove_label.py --input ./frames --output ./frames-clean
    python remove_label.py --input clip.mp4 --output clip.mp4 --dry-run --json

退出码：0 干净（或未检出标），2 处理后仍有残留，3 参数/环境问题。

依赖：Pillow；视频处理需要 ffmpeg（PATH 里，或用 FFMPEG 环境变量指定）。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops, ImageFilter

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm")
FF_CANDIDATES = (
    os.environ.get("FFMPEG"),
    r"D:\Programs\ffmpeg\ffmpeg-9.0.2-full_build\bin\ffmpeg.EXE",
    r"D:\workbuddy\runtime\ffmpeg\ffmpeg.exe",
    "/usr/bin/ffmpeg",
)

# 检测参数：用「比周围亮多少」（高通）而不是绝对亮度——纸面、白底本身就亮，
# 绝对阈值一上去整片背景都算命中；纯二维 bbox 又会被纸纤维误判。
# 这里改成「只看右侧竖条带，逐行数热点，从底往上走」——文字行每行都有几十个热点，
# 纸纹只是零星几个，靠行剖面就能分开。
STRIP_W = 0.18       # 只看右侧 18% 宽的竖条带
ROW_HOT = 3          # 一行里热点像素超过这个数算「有字」
GAP_ROWS = 40        # 连续这么多行没字才认为到顶（两行字之间有空隙，别切太早）
MAX_LABEL_H = 0.16   # 标签块高度上限（占画面高），超过视为误判

# 裁多少：这个标是固定像素图章（图约 110x52，视频流里约 167x75），
# 又贴着底边，所以「固定像素兜底 + 按高度比例兜底，取大」最稳。
# 检测只用来报告实际位置，不直接决定裁多少——纸纹、亮地面会把它带偏。
CUT_PX = {"image": 80, "video": 100}
CUT_FRAC = {"image": 0.055, "video": 0.075}


def find_ffmpeg():
    for cand in FF_CANDIDATES:
        if cand and os.path.isfile(cand):
            return cand
    got = shutil.which("ffmpeg")
    if got:
        return got
    return None


def diff_image(im):
    gray = im.convert("L")
    bg = gray.filter(ImageFilter.MedianFilter(15))
    return gray, ImageChops.difference(gray, bg)


def label_top(im):
    """从底部往上走，返回标签块上边界（绝对行号）；检不出返回 None。"""
    w, h = im.size
    _, diff = diff_image(im)
    strip = diff.crop((int(w * (1 - STRIP_W)), 0, w, h))
    mask = strip.point(lambda v: 255 if v > 18 else 0)
    # 逐行热点数（标签不贴底边，先跳过底部空白，再往上走）
    rows = []
    px = mask.load()
    sw, sh = mask.size
    for y in range(sh):
        c = 0
        for x in range(sw):
            if px[x, y]:
                c += 1
        rows.append(c)

    y = sh - 1
    while y >= 0 and rows[y] <= ROW_HOT:      # 跳过底部空白（标签不贴边）
        y -= 1
    if y < 0:
        return None
    bottom = y
    top = y
    gap = 0
    while y >= 0:
        if rows[y] > ROW_HOT:
            top = y
            gap = 0
        else:
            gap += 1
            if gap > GAP_ROWS:
                break
        y -= 1
    height = bottom - top + 1
    if height < 10 or height > MAX_LABEL_H * h:
        return None                            # 太薄像噪点，太厚像纸纹
    if (h - top) > 0.25 * h:                   # 标签不可能离底边这么远
        return None
    return top


def cut_amount(kind, height, pad):
    """底部裁多少像素：固定像素兜底与比例兜底取大，再夹到合理区间。"""
    return max(8, CUT_PX[kind], int(height * CUT_FRAC[kind]),
               min(int(height * 0.25), CUT_PX[kind] + pad))


def hot_density(im, band_w=0.10, band_h=0.07):
    """右下角带内的「热点密度」，用来判断标还在不在。"""
    w, h = im.size
    box = (int(w * (1 - band_w)), int(h * (1 - band_h)), w, h)
    m = measure_region(im, box, pad=0)
    area = max(1, m["px"])
    return m["hot"] / float(area), m


def measure_region(im, box, pad=6):
    """量框内「比周围亮 18 以上」的像素数和最高亮度，用于前后对比。"""
    w, h = im.size
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(w, x1 + pad), min(h, y1 + pad)
    gray, diff = diff_image(im)
    sub = diff.crop((x0, y0, x1, y1)).point(lambda v: 255 if v > 18 else 0)
    hot = sub.histogram()[255]
    g = gray.crop((x0, y0, x1, y1)).histogram()
    peak = 0
    for v in range(255, -1, -1):
        if g[v]:
            peak = v
            break
    return dict(px=sub.size[0] * sub.size[1], hot=hot, peak=peak, box=[x0, y0, x1, y1])


def cover_size(src_w, src_h, dst_w, dst_h):
    s = max(dst_w / float(src_w), dst_h / float(src_h))
    return int(round(src_w * s)), int(round(src_h * s))


def process_image(src, dst, keep_size, size, pad):
    im = Image.open(src).convert("RGB")
    W, H = im.size
    top = label_top(im)
    report = dict(src=src, out=dst, kind="image", size=[W, H], label_top=top)
    corner = (int(W * 0.85), top if top is not None else int(H * 0.90), W, H)
    before = measure_region(im, corner)

    density0, _ = hot_density(im, 0.10, 0.055)
    report["density0"] = round(density0, 4)
    if top is None and density0 < 0.01:          # 角落本来就干净，别白裁一刀
        if os.path.abspath(src) != os.path.abspath(dst):
            im.save(dst) if dst.lower().endswith(".png") else im.save(dst, quality=95)
        report.update(status="no-label")
        return report, True
    cut = cut_amount("image", H, pad)
    if top is None:
        report["detected"] = "none"
    ch = H - cut
    if ch <= 100:
        raise SystemExit("裁切后高度异常 %d，检查 --pad" % ch)

    tw, th = (W, H) if keep_size else (W, ch)
    if size:
        tw, th = [int(v) for v in size.lower().split("x")]
    cropped = im.crop((0, 0, W, ch))
    if (tw, th) != cropped.size:
        nw, nh = cover_size(cropped.width, cropped.height, tw, th)
        cropped = cropped.resize((nw, nh), Image.LANCZOS)
        left = (nw - tw) // 2
        ctop = (nh - th) // 2
        cropped = cropped.crop((left, ctop, left + tw, ctop + th))

    fmt = "PNG" if dst.lower().endswith(".png") else None
    if fmt == "PNG":
        cropped.save(dst, fmt)
    else:
        cropped.save(dst, quality=95)

    after_im = Image.open(dst).convert("RGB")
    db, _ = hot_density(im, 0.10, 0.055)
    da, mb = hot_density(after_im, 0.10, 0.055)
    report.update(cut_px=cut, out_size=[tw, th], before=before,
                  after=mb, density=[round(db, 4), round(da, 4)])
    ok = da <= max(0.0025, db * 0.5)
    report.update(status="clean" if ok else "residual")
    return report, ok


def probe_size(ff, path):
    """在 ffmpeg 同目录找 ffprobe；找不到就用 ffmpeg -i 的 stderr 兜底。"""
    folder, name = os.path.split(ff)
    cand = os.path.join(folder, name.replace("ffmpeg", "ffprobe"))
    if os.path.isfile(cand):
        out = subprocess.run([cand, "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=width,height",
                              "-of", "csv=p=0", path], capture_output=True, text=True)
        txt = out.stdout.strip().splitlines()
        if txt:
            parts = txt[0].split(",")
            return int(parts[0]), int(parts[1])
        return None, None
    out = subprocess.run([ff, "-i", path], capture_output=True, text=True)
    import re
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out.stderr)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def grab_frame(ff, path, t, dst):
    subprocess.run([ff, "-y", "-v", "error", "-ss", "%.2f" % t, "-i", path,
                    "-frames:v", "1", dst], check=True)
    return Image.open(dst).convert("RGB")


def process_video(src, dst, keep_size, size, pad):
    ff = find_ffmpeg()
    if not ff:
        raise SystemExit("找不到 ffmpeg，装一个或设 FFMPEG 环境变量")
    W, H = probe_size(ff, src)
    if not W:
        raise SystemExit("读不到视频尺寸：%s" % src)

    tmp = tempfile.mkdtemp(prefix="rmlabel_")
    try:
        frames = [grab_frame(ff, src, t, os.path.join(tmp, "f%d.png" % i))
                  for i, t in enumerate((0.3, 0.5, 0.7))]
        tops = [t for t in (label_top(f) for f in frames) if t is not None]
        report = dict(src=src, out=dst, kind="video", size=[W, H], frames=[W, H],
                      label_tops=tops or None)

        before = measure_region(frames[1], (int(W * 0.85),
                                           min(tops) if tops else int(H * 0.90), W, H))
        density0, _ = hot_density(frames[1], 0.10, 0.09)
        report["density0"] = round(density0, 4)
        if not tops and density0 < 0.01:         # 角落本来就干净，别白裁
            if os.path.abspath(src) != os.path.abspath(dst):
                shutil.copyfile(src, dst)
            report.update(status="no-label")
            return report, True
        cut = cut_amount("video", H, pad)
        ch = H - cut
        if ch <= 100:
            raise SystemExit("裁切后高度异常 %d，检查 --pad" % ch)

        tw, th = (W, H) if keep_size else (W, ch)
        if size:
            tw, th = [int(v) for v in size.lower().split("x")]

        vf = "crop=%d:%d:0:0" % (W, ch)
        if (tw, th) != (W, ch):
            vf += (",scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos"
                   ",crop=%d:%d" % (tw, th, tw, th))
        cmd = [ff, "-y", "-v", "error", "-i", src, "-vf", vf,
               "-c:v", "libx264", "-preset", "medium", "-crf", "17",
               "-pix_fmt", "yuv420p", "-an", dst]
        subprocess.run(cmd, check=True)

        after_frame = grab_frame(ff, dst, 0.5, os.path.join(tmp, "after.png"))
        db, _ = hot_density(frames[1], 0.10, 0.09)
        da, mb = hot_density(after_frame, 0.10, 0.09)
        report.update(cut_px=cut, out_size=[tw, th], before=before,
                      after=mb, density=[round(db, 4), round(da, 4)])
        ok = da <= max(0.0025, db * 0.5)
        report.update(status="clean" if ok else "residual")
        return report, ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="去掉右下角「AI生成 / WORKBUDDY」标")
    ap.add_argument("--input", required=True, help="文件或目录")
    ap.add_argument("--output", required=True, help="文件或目录（目录模式一一对应）")
    ap.add_argument("--pad", type=int, default=6, help="水印上边界之外再留几像素，默认 6")
    ap.add_argument("--keep-size", action="store_true", default=True,
                    help="裁完用 cover 缩放铺回原尺寸（默认开，不拉伸）")
    ap.add_argument("--no-keep-size", dest="keep_size", action="store_false",
                    help="保留裁后的实际尺寸，不缩放")
    ap.add_argument("--size", default="", help="强制输出尺寸，如 1920x1080")
    ap.add_argument("--dry-run", action="store_true", help="只测不写")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.dry_run and os.path.isdir(a.input):
        raise SystemExit("--dry-run 只支持单文件")

    targets = []
    if os.path.isdir(a.input):
        os.makedirs(a.output, exist_ok=True)
        for name in sorted(os.listdir(a.input)):
            low = name.lower()
            if low.endswith(IMAGE_EXT) or low.endswith(VIDEO_EXT):
                targets.append((os.path.join(a.input, name), os.path.join(a.output, name)))
        if not targets:
            raise SystemExit("目录里没有可处理的图片/视频：%s" % a.input)
    else:
        if not os.path.isfile(a.input):
            raise SystemExit("文件不存在：%s" % a.input)
        targets.append((a.input, a.output))

    reports, fails = [], 0
    for src, dst in targets:
        is_video = src.lower().endswith(VIDEO_EXT)
        try:
            if a.dry_run:
                if is_video:
                    ff = find_ffmpeg()
                    if not ff:
                        raise SystemExit("找不到 ffmpeg")
                    tmp = tempfile.mkdtemp(prefix="rmlabel_")
                    try:
                        f = grab_frame(ff, src, 0.5, os.path.join(tmp, "d.png"))
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)
                    img, kind, size = f, "video", None
                else:
                    img = Image.open(src).convert("RGB")
                    kind, size = "image", list(img.size)
                top = label_top(img)
                rep = dict(src=src, kind=kind, size=size, label_top=top,
                           status="label" if top is not None else "no-label")
                if top is not None:
                    rep["metrics"] = measure_region(
                        img, (int(img.size[0] * 0.85), top, img.size[0], img.size[1]))
            else:
                rep, ok = (process_video if is_video else process_image)(
                    src, dst, a.keep_size, a.size, a.pad)
                if not ok:
                    fails += 1
        except SystemExit:
            raise
        except Exception as exc:                       # noqa: BLE001
            rep = dict(src=src, status="error", error=str(exc))
            fails += 1
        reports.append(rep)
        if not a.json:
            print(format_line(rep))

    if a.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0],
                         ensure_ascii=False, indent=1))
    sys.exit(2 if fails else 0)


def format_line(rep):
    name = os.path.basename(rep.get("src", "?"))
    st = rep.get("status")
    if st == "no-label":
        return "%-28s 未检出右下角标" % name
    if st == "error":
        return "%-28s 失败：%s" % (name, rep.get("error"))
    if st in ("clean", "residual"):
        b, af = rep.get("before", {}), rep.get("after", {})
        return ("%-28s 裁 %dpx → %s  亮像素 %d→%d  峰值 %d→%d  %s"
                % (name, rep.get("cut_px", 0), "x".join(str(v) for v in rep.get("out_size", [])),
                   b.get("hot", 0), af.get("hot", 0), b.get("peak", 0), af.get("peak", 0),
                   "干净" if st == "clean" else "仍有残留"))
    return "%-28s %s" % (name, st)


if __name__ == "__main__":
    main()
