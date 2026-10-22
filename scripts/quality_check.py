#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成片质检：规格 / 响度 / 黑帧 / 冻结帧 / 字幕几何，一次跑完出 report.json。

    python quality_check.py out/final.mp4 --expect 1920x1080 --fps 24 --lufs -14
    python quality_check.py out/final.mp4 --lines out/lines.json    # 顺带查字幕是否越界

只做"能量化"的检查。镜头好不好看、剧情通不通，脚本管不了，必须人看。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys


def find_ffmpeg():
    for cand in (r"D:/workbuddy/runtime/ffmpeg/ffmpeg.exe",
                 shutil.which("ffmpeg"),
                 r"C:/Users/Admin/.workbuddy/binaries/ffmpeg/ffmpeg.exe",
                 r"C:/Users/Admin/.local/bin/ffmpeg.exe"):
        if cand and os.path.exists(cand):
            return cand
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("找不到 ffmpeg")


FF = find_ffmpeg()


def run(args):
    r = subprocess.run([FF, "-hide_banner"] + args, capture_output=True, text=True,
                       errors="ignore")
    return (r.stdout or "") + (r.stderr or "")


def probe(path):
    txt = run(["-i", path])
    d = {}
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", txt)
    if m:
        h, mi, s = m.groups()
        d["duration"] = round(int(h) * 3600 + int(mi) * 60 + float(s), 3)
    mv = re.search(r"Video: (\w+).*?(\d{2,5})x(\d{2,5})", txt)
    if mv:
        d["vcodec"] = mv.group(1)
        d["width"], d["height"] = int(mv.group(2)), int(mv.group(3))
        line = txt[mv.start():txt.find("\n", mv.start())]
        mf = re.search(r"([\d.]+)\s+fps", line)
        if mf:
            d["fps"] = round(float(mf.group(1)), 3)
    ma = re.search(r"Audio: (\w+)", txt)
    if ma:
        d["acodec"] = ma.group(1)
        msr = re.search(r"Audio:.*?, (\d+) Hz", txt)
        if msr:
            d["sample_rate"] = int(msr.group(1))
    return d


def loudness(path):
    txt = run(["-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"])
    out = {}
    m = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", txt)
    if m:
        out["integrated_lufs"] = float(m[-1])
    m = re.findall(r"LRA:\s*(-?[\d.]+)\s*LU", txt)
    if m:
        out["lra"] = float(m[-1])
    m = re.findall(r"Peak:\s*(-?[\d.]+)\s*dBFS", txt)
    if m:
        out["true_peak_dbfs"] = float(m[-1])
    return out


def black_frames(path, ignore_head, ignore_tail, dur):
    txt = run(["-i", path, "-vf", "blackdetect=d=0.12:pix_th=0.10", "-an", "-f", "null", "-"])
    segs = []
    for m in re.finditer(r"black_start:([\d.]+)\s+black_end:([\d.]+)", txt):
        a, b = float(m.group(1)), float(m.group(2))
        if a < ignore_head or b > dur - ignore_tail:
            continue
        segs.append([round(a, 2), round(b, 2)])
    return segs


def freeze_frames(path, dur):
    txt = run(["-i", path, "-vf", "freezedetect=n=0.004:d=2.0", "-an", "-f", "null", "-"])
    segs = []
    for m in re.finditer(r"freeze_start:\s*([\d.]+)", txt):
        segs.append(round(float(m.group(1)), 2))
    return segs


def check_caption_geometry(lines, width, height, safe_x=30, safe_top=8, safe_bottom=8):
    """用 lines.json 的 x/y/fs 估算纸卡外框，查是否越界 / 压到底边。"""
    problems = []
    for it in lines:
        fs = int(it.get("fs", 66))
        n = len([c for c in it.get("text", "") if c.strip()])
        scene = it.get("mode") == "scene"
        cw = fs * 1.06 if scene else fs + 2 * round(fs * 0.24)
        total = n * cw + (n - 1) * (-6)
        x, y = float(it.get("x", 960)), float(it.get("y", 1000))
        left, right = x - total / 2, x + total / 2
        top, bottom = y - fs * 0.75, y + fs * 0.75
        if left < safe_x or right > width - safe_x:
            problems.append({"text": it["text"][:12], "issue": "横向越界",
                             "left": round(left), "right": round(right)})
        if bottom > height - safe_bottom:
            problems.append({"text": it["text"][:12], "issue": "压到底边",
                             "bottom": round(bottom)})
        if top < safe_top:
            problems.append({"text": it["text"][:12], "issue": "压到顶边",
                             "top": round(top)})
        if fs < 48:
            problems.append({"text": it["text"][:12], "issue": "字号过小", "fs": fs})
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--expect", default=None, help="如 1920x1080")
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--dur-tol", dest="dur_tol", type=float, default=0.3)
    ap.add_argument("--lufs", type=float, default=-14.0)
    ap.add_argument("--lufs-tol", dest="lufs_tol", type=float, default=1.5)
    ap.add_argument("--peak-max", dest="peak_max", type=float, default=-1.0)
    ap.add_argument("--lines", help="lines.json，顺带查字幕几何")
    ap.add_argument("--ignore-head", dest="ignore_head", type=float, default=1.6)
    ap.add_argument("--ignore-tail", dest="ignore_tail", type=float, default=2.8)
    ap.add_argument("-o", "--out", default="out/report.json")
    a = ap.parse_args()

    info = probe(a.video)
    dur = info.get("duration", 0)
    fails, warns = [], []

    # 1) 规格
    if a.expect:
        try:
            w, h = [int(v) for v in a.expect.lower().split("x")]
            if (info.get("width"), info.get("height")) != (w, h):
                fails.append("分辨率 %sx%s != 期望 %dx%d"
                             % (info.get("width"), info.get("height"), w, h))
        except Exception:
            warns.append("--expect 写法应是 1920x1080")
    if a.fps and abs((info.get("fps") or 0) - a.fps) > 0.01:
        fails.append("帧率 %s != 期望 %s" % (info.get("fps"), a.fps))
    if a.duration and abs(dur - a.duration) > a.dur_tol:
        fails.append("时长 %.2f != 期望 %.2f" % (dur, a.duration))

    # 2) 响度
    ld = loudness(a.video)
    if "integrated_lufs" in ld and abs(ld["integrated_lufs"] - a.lufs) > a.lufs_tol:
        fails.append("整体响度 %.1f LUFS，偏离目标 %.1f 超过 %.1f"
                     % (ld["integrated_lufs"], a.lufs, a.lufs_tol))
    if ld.get("true_peak_dbfs", -99) > a.peak_max:
        fails.append("真峰值 %.1f dBFS 超过 %.1f（会削波）"
                     % (ld["true_peak_dbfs"], a.peak_max))
    if not info.get("acodec"):
        fails.append("没有音轨")

    # 3) 黑帧 / 冻结
    blacks = black_frames(a.video, a.ignore_head, a.ignore_tail, dur)
    if blacks:
        fails.append("非预期黑帧 %d 处: %s" % (len(blacks), blacks[:5]))
    freezes = freeze_frames(a.video, dur)
    if freezes:
        warns.append("疑似卡住 %d 处（>2s 无变化，慢镜头可忽略）: %s"
                     % (len(freezes), freezes[:6]))

    # 4) 字幕几何
    cap_prob = []
    if a.lines:
        lines = json.load(open(a.lines, encoding="utf-8"))
        cap_prob = check_caption_geometry(lines, info.get("width", 1920),
                                          info.get("height", 1080))
        if cap_prob:
            fails.append("字幕几何问题 %d 处" % len(cap_prob))

    report = {"video": a.video, "probe": info, "loudness": ld,
              "black_frames": blacks, "freeze_points": freezes,
              "caption_problems": cap_prob[:40],
              "fails": fails, "warnings": warns,
              "pass": not fails}

    print("== 质检 %s ==" % a.video)
    print("  %sx%s @%sfps  %.2fs  %s / %s"
          % (info.get("width"), info.get("height"), info.get("fps"), dur,
             info.get("vcodec"), info.get("acodec")))
    print("  响度 %.1f LUFS  LRA %.1f  峰值 %.1f dBFS"
          % (ld.get("integrated_lufs", 0), ld.get("lra", 0), ld.get("true_peak_dbfs", 0)))
    print("  黑帧 %d 处  冻结 %d 处  字幕问题 %d 处"
          % (len(blacks), len(freezes), len(cap_prob)))
    for f in fails:
        print("  [不通过]", f)
    for w in warns:
        print("  [注意]", w)
    print("  结论:", "通过" if report["pass"] else "不通过")

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  报告 →", a.out)
    sys.exit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
