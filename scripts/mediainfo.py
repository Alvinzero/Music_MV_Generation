#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""素材体检：读出真实规格，不猜、不靠肉眼。

    python inspect.py assets/ -o out/manifest.json
    python inspect.py a.mp4 b.mp3 --json      # 只看结果不落盘

有 ffprobe 就用 ffprobe，没有就降级解析 `ffmpeg -i` 的 stderr（本机常见情况）。
输出 manifest.json 是后续 timeline / render / quality_check 的输入。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


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
        return None


def find_ffprobe():
    for cand in (shutil.which("ffprobe"),
                 r"C:/Users/Admin/.workbuddy/binaries/ffmpeg/ffprobe.exe"):
        if cand and os.path.exists(cand):
            return cand
    return None


FF = find_ffmpeg()
FP = find_ffprobe()
if not FF:
    sys.exit("找不到 ffmpeg。装一个：pip install imageio-ffmpeg")


def probe_ffprobe(path):
    r = subprocess.run([FP, "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", path],
                       capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    fmt = j.get("format", {})
    info = {"duration": float(fmt.get("duration") or 0),
            "bitrate": int(float(fmt.get("bit_rate") or 0)),
            "width": None, "height": None, "fps": None,
            "vcodec": None, "acodec": None, "has_audio": False,
            "sample_rate": None, "channels": None}
    for s in j.get("streams", []):
        if s.get("codec_type") == "video" and info["width"] is None:
            info["width"], info["height"] = s.get("width"), s.get("height")
            info["vcodec"] = s.get("codec_name")
            fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
            try:
                n, d = fr.split("/")
                info["fps"] = round(float(n) / float(d), 3) if float(d) else None
            except Exception:
                info["fps"] = None
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
            info["acodec"] = s.get("codec_name")
            info["sample_rate"] = int(s.get("sample_rate") or 0)
            info["channels"] = s.get("channels")
    return info


RE_DUR = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")
RE_VID = re.compile(r"Stream #\d+:\d+.*?: Video: ([a-zA-Z0-9_]+).*?(\d{2,5})x(\d{2,5})")
RE_FPS = re.compile(r"([\d.]+)\s+fps")
RE_AUD = re.compile(r"Stream #\d+:\d+.*?: Audio: ([a-zA-Z0-9_]+)")


def probe_ffmpeg(path):
    """降级路径：解析 ffmpeg -i 的 stderr。"""
    r = subprocess.run([FF, "-hide_banner", "-i", path],
                       capture_output=True, text=True, errors="ignore")
    txt = r.stderr
    info = {"duration": 0.0, "bitrate": 0, "width": None, "height": None,
            "fps": None, "vcodec": None, "acodec": None, "has_audio": False,
            "sample_rate": None, "channels": None}
    m = RE_DUR.search(txt)
    if m:
        h, mi, s = m.groups()
        info["duration"] = round(int(h) * 3600 + int(mi) * 60 + float(s), 3)
    mv = RE_VID.search(txt)
    if mv:
        info["vcodec"] = mv.group(1)
        info["width"], info["height"] = int(mv.group(2)), int(mv.group(3))
        line = txt[mv.start():txt.find("\n", mv.start())]
        mf = RE_FPS.search(line)
        if mf:
            info["fps"] = round(float(mf.group(1)), 3)
    ma = RE_AUD.search(txt)
    if ma:
        info["has_audio"] = True
        info["acodec"] = ma.group(1)
    return info


def probe(path):
    if FP:
        try:
            return probe_ffprobe(path)
        except Exception:
            pass
    return probe_ffmpeg(path)


def kind(path):
    e = os.path.splitext(path)[1].lower()
    if e in VIDEO_EXT:
        return "video"
    if e in AUDIO_EXT:
        return "audio"
    if e in IMAGE_EXT:
        return "image"
    return "other"


def collect(targets):
    files = []
    for t in targets:
        if os.path.isdir(t):
            for root, _, names in os.walk(t):
                for n in sorted(names):
                    if kind(n) in ("video", "audio", "image"):
                        files.append(os.path.join(root, n))
        elif os.path.isfile(t):
            files.append(t)
        else:
            print("跳过不存在的路径:", t)
    return sorted(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("-o", "--out", default="out/manifest.json")
    ap.add_argument("--json", action="store_true", help="只打印，不写文件")
    a = ap.parse_args()

    files = collect(a.targets)
    if not files:
        sys.exit("没找到可分析的媒体文件")

    items, warn = [], []
    for f in files:
        k = kind(f)
        rec = {"path": f.replace("\\", "/"), "name": os.path.basename(f),
               "kind": k, "size_mb": round(os.path.getsize(f) / 1048576, 2)}
        if k in ("video", "audio"):
            rec.update(probe(f))
        items.append(rec)

    vids = [i for i in items if i["kind"] == "video"]
    auds = [i for i in items if i["kind"] == "audio"]

    # ---- 一致性检查：混素材最容易在这里翻车 ----
    if vids:
        sizes = {(i["width"], i["height"]) for i in vids}
        fpss = {i["fps"] for i in vids}
        if len(sizes) > 1:
            warn.append("分辨率不一致: %s" % sorted(sizes))
        if len(fpss) > 1:
            warn.append("帧率不一致: %s" % sorted(fpss))
        short = [i["name"] for i in vids if (i["duration"] or 0) < 1.0]
        if short:
            warn.append("%d 个片段短于 1 秒: %s" % (len(short), short[:5]))
        noaudio = [i["name"] for i in vids if not i["has_audio"]]
        if noaudio and len(noaudio) == len(vids):
            warn.append("全部片段无音轨（正常，最终用外部音轨混音）")
        odd = [i["name"] for i in vids if (i["fps"] or 0) not in (24, 25, 30, 50, 60, 23.976)]
        if odd:
            warn.append("非标准帧率: %s" % odd[:5])

    total = round(sum(i.get("duration") or 0 for i in vids), 3)
    manifest = {
        "generator": "video-finisher/inspect.py",
        "ffmpeg": FF, "ffprobe": FP,
        "summary": {"videos": len(vids), "audios": len(auds),
                    "images": len([i for i in items if i["kind"] == "image"]),
                    "video_total_seconds": total,
                    "canvas": {"width": vids[0]["width"], "height": vids[0]["height"],
                               "fps": vids[0]["fps"]} if vids else None},
        "warnings": warn,
        "items": items,
    }

    print("%-42s %-6s %8s  %s" % ("文件", "类型", "时长", "规格"))
    for i in items:
        spec = ("%sx%s@%s" % (i.get("width"), i.get("height"), i.get("fps"))
                if i["kind"] == "video" else (i.get("acodec") or ""))
        print("%-42s %-6s %8.2f  %s" % (i["name"][:41], i["kind"],
                                        i.get("duration") or 0, spec))
    print("\n片段 %d 个，合计 %.2fs；音频 %d 个" % (len(vids), total, len(auds)))
    for w in warn:
        print("  [警告]", w)

    if not a.json:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump(manifest, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("写入", a.out)


if __name__ == "__main__":
    main()
