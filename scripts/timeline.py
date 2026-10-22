#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timeline.json 的生成与校验 —— AI 和渲染器之间唯一的合同。

    # 从素材自动排（每个片段用全长，按文件名顺序）
    python timeline.py build --manifest out/manifest.json --fps 24 \
        --audio song.m4a --lines out/lines.json -o out/timeline.json

    # 手工指定切点（秒）
    python timeline.py build --cuts out/cuts.json --fps 24 --duration 292.01 \
        --audio song.m4a -o out/timeline.json

    # 校验
    python timeline.py check out/timeline.json

约定：
  * 一切时间以「帧」为整数存，"秒"只是镜像字段（*_sec），仅用于人读。
  * start_frame 是成片时间轴上的位置；in_frame/out_frame 是素材内部取用区间。
  * 叠化时长记在「后一个镜头」的 xfade 上，渲染时 offset = start_frame。
"""
import argparse
import json
import math
import os
import sys

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def sec2f(t, fps):
    return int(round(float(t) * fps))


def f2sec(f, fps):
    return round(f / float(fps), 3)


def off_sec(frame, fps):
    ms = int(round(frame * 1000.0 / fps))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%d:%02d:%02d.%03d" % (h, m, s, ms)


def dur_frames(seg):
    """镜头在成片时间轴上占多少帧。speed < 1 表示慢放（拉长）。"""
    sp = float(seg.get("speed", 1.0)) or 1.0
    return int(round((seg["out_frame"] - seg["in_frame"]) / sp))


def load(p):
    return json.load(open(p, encoding="utf-8"))


def build_from_manifest(man, fps, fade_frames):
    clips = [i for i in man["items"] if i["kind"] == "video"]
    if not clips:
        sys.exit("manifest 里没有视频片段")
    out, cursor = [], 0
    for k, c in enumerate(clips):
        dur = int(round((c.get("duration") or 0) * fps))
        if dur <= 0:
            print("跳过零长片段", c["name"])
            continue
        seg = {"id": "s%02d" % (k + 1), "file": c["path"],
               "in_frame": 0, "out_frame": dur, "speed": 1.0, "start_frame": cursor}
        if k > 0:
            seg["xfade"] = {"type": "fade", "frames": fade_frames}
        out.append(seg)
        cursor += dur - (fade_frames if k < len(clips) - 1 else 0)
    return out, cursor


def build_from_cuts(cuts, fps, fade_frames, slot_mode=True, src_dur=None):
    out, cursor = [], 0
    for k, c in enumerate(cuts):
        if "start_frame" in c:
            a = int(c["start_frame"])
            b = int(c["end_frame"])
        else:
            a = sec2f(c.get("start", 0), fps)
            b = sec2f(c.get("end", 0), fps)
        dur = b - a
        if dur <= 0:
            sys.exit("片段 %s 的 end <= start" % c.get("file"))
        out_b = b
        speed = 1.0
        need = (b - a) + (fade_frames if (slot_mode and k < len(cuts) - 1) else 0)
        avail = (src_dur or {}).get(os.path.basename(c["file"]))
        if slot_mode:
            out_b = b + (fade_frames if k < len(cuts) - 1 else 0)
            if avail:
                capf = int(round(avail * fps))
                if out_b > capf:          # 素材不够长 → 慢放
                    # 要的是"屏上 = out_b 帧"，所以 speed = 可用帧 / 目标帧
                    speed = round(capf / float(out_b), 4)
                    out_b = capf
                    if speed > 2.5:
                        print("  [警告] %s 需要 %.2fx 慢放（超过 2.5x 建议补拍）"
                              % (os.path.basename(c["file"]), speed))
        seg = {"id": c.get("id") or "s%02d" % (k + 1), "file": c["file"],
               "in_frame": a, "out_frame": out_b, "speed": speed,
               "start_frame": int(c["start_frame"]) if "start_frame" in c else cursor}
        if k > 0 and c.get("xfade", True):
            seg["xfade"] = {"type": c.get("xfade_type", "fade"),
                            "frames": int(c.get("xfade_frames", fade_frames))}
        out.append(seg)
        # 下一镜要提前 fade 帧开始，才能与当前镜头交叠
        # 推进量 = 屏上时长 − 与下一镜的交叠（叠化记在下一个镜头上）
        next_fade = 0
        if k < len(cuts) - 1:
            nxt = cuts[k + 1]
            next_fade = int(nxt.get("xfade_frames", fade_frames)) if nxt.get("xfade", True) else 0
        cursor = seg["start_frame"] + dur_frames(seg) - next_fade
    return out, cursor


def attach_captions(tl, lines, fps):
    caps = []
    for it in lines:
        s = sec2f(it["start"], fps)
        e = max(sec2f(it["end"], fps), s + 1)
        cap = {"text": it["text"], "start_frame": s, "end_frame": e}
        if it.get("times"):
            cap["chars"] = [{"c": c, "f": sec2f(t, fps)}
                            for c, t in zip(
                                [x for x in it["text"] if x.strip()], it["times"])
                            if c]
        for k in ("x", "y", "fs", "accent", "mode", "ink", "edge"):
            if k in it:
                cap[k] = it[k]
        caps.append(cap)
    caps.sort(key=lambda c: c["start_frame"])
    tl["captions"] = caps
    return tl


def cmd_build(a):
    fps = a.fps
    fade = sec2f(a.fade, fps)
    if a.cuts:
        cuts = load(a.cuts)
        src_dur = {}
        if a.manifest:
            for it in load(a.manifest).get("items", []):
                if it.get("duration"):
                    src_dur[it["name"]] = it["duration"]
        segs, cursor = build_from_cuts(cuts, fps, fade,
                                       slot_mode=not a.raw_range, src_dur=src_dur)
    else:
        if not a.manifest:
            sys.exit("要么给 --manifest，要么给 --cuts")
        man = load(a.manifest)
        segs, cursor = build_from_manifest(man, fps, fade)

    # 目标总长：用 --duration 反推最后一个镜头的 out_frame
    if a.duration:
        target = sec2f(a.duration, fps)
        if segs:
            last = segs[-1]
            need = target - last["start_frame"]
            if need > 0:
                last["out_frame"] = last["in_frame"] + need
                cursor = target
            else:
                print("[警告] 素材总长 %.2fs 超过目标 %.2fs，尾段会被裁掉"
                      % (f2sec(cursor, fps), a.duration))
                segs = [s for s in segs if s["start_frame"] < target]
                segs[-1]["out_frame"] = segs[-1]["in_frame"] + (target - segs[-1]["start_frame"])
                cursor = target
    else:
        target = cursor

    tl = {"version": 1,
          "generator": "video-finisher/timeline.py",
          "canvas": {"width": a.width, "height": a.height, "fps": fps},
          "duration_frames": int(target),
          "duration_sec": f2sec(target, fps),
          "audio": {"music": a.audio, "voice": a.voice,
                    "loudnorm": {"I": -14, "TP": -1.0, "LRA": 11},
                    "fade_in_sec": a.fade_in, "fade_out_sec": a.fade_out},
          "video": segs,
          "captions": []}

    # 秒镜像
    for s in segs:
        s["start_sec"] = f2sec(s["start_frame"], fps)
        s["dur_sec"] = f2sec(dur_frames(s), fps)

    if a.lines:
        attach_captions(tl, load(a.lines), fps)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(tl, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("镜头 %d 个，字幕 %d 条，总长 %.3fs (%d 帧) → %s"
          % (len(segs), len(tl["captions"]), tl["duration_sec"],
             tl["duration_frames"], a.out))
    return 0 if cmd_check(a.out, quiet=False) else 1


def cmd_check(path, quiet=False):
    tl = load(path)
    fps = tl["canvas"]["fps"]
    total = tl["duration_frames"]
    errs, warns = [], []
    segs = tl.get("video", [])

    for s in segs:
        if not os.path.exists(s["file"]):
            errs.append("素材不存在: %s" % s["file"])
        if s["out_frame"] <= s["in_frame"]:
            errs.append("%s: out_frame <= in_frame" % s["id"])
        sp = float(s.get("speed", 1.0))
        if sp <= 0 or sp > 2.5:
            errs.append("%s: speed=%.2f 超出 0~2.5（更快会糊，更慢建议补拍）" % (s["id"], sp))
        elif sp < 0.999:
            warns.append("%s 慢放 %.2fx（%.2fs → %.2fs）"
                         % (s["id"], sp, (s["out_frame"] - s["in_frame"]) / float(fps),
                            dur_frames(s) / float(fps)))
        if s["start_frame"] < 0:
            errs.append("%s: start_frame < 0" % s["id"])

    for i in range(1, len(segs)):
        prev_end = segs[i - 1]["start_frame"] + dur_frames(segs[i - 1])
        xf = segs[i].get("xfade", {}).get("frames", 0)
        if segs[i]["start_frame"] + xf != prev_end:
            errs.append("%s 与上一镜不对齐：应为 %d，实际 %d"
                        % (segs[i]["id"], prev_end - xf, segs[i]["start_frame"]))

    caps = tl.get("captions", [])
    for k, c in enumerate(caps):
        if c["end_frame"] <= c["start_frame"]:
            errs.append("字幕 %d 时长为 0: %s" % (k, c["text"][:12]))
        if c["start_frame"] >= total:
            errs.append("字幕 %d 超出片长: %s" % (k, c["text"][:12]))
        if k and c["start_frame"] < caps[k - 1]["end_frame"]:
            warns.append("字幕重叠 %.2fs: %s / %s"
                         % (f2sec(caps[k - 1]["end_frame"] - c["start_frame"], fps),
                            caps[k - 1]["text"][:8], c["text"][:8]))
        if c.get("chars"):
            fs = [x["f"] for x in c["chars"]]
            if fs != sorted(fs):
                errs.append("字幕 %d 的逐字时间不递增" % k)

    if not quiet or errs:
        print("== 校验 %s ==" % path)
        print("  画布 %dx%d @%sfps  总长 %.3fs (%d 帧)  镜头 %d  字幕 %d"
              % (tl["canvas"]["width"], tl["canvas"]["height"], fps,
                 total / fps, total, len(segs), len(caps)))
        for w in warns[:12]:
            print("  [警告]", w)
        if len(warns) > 12:
            print("  [警告] ... 共 %d 条" % len(warns))
        for e in errs[:20]:
            print("  [错误]", e)
        print("  结论:", "通过" if not errs else "有 %d 处错误" % len(errs))
    return not errs


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--manifest")
    b.add_argument("--cuts")
    b.add_argument("--lines")
    b.add_argument("--audio")
    b.add_argument("--voice")
    b.add_argument("--fps", type=float, default=24)
    b.add_argument("--width", type=int, default=1920)
    b.add_argument("--height", type=int, default=1080)
    b.add_argument("--fade", type=float, default=0.5, help="叠化秒数")
    b.add_argument("--fade-in", dest="fade_in", type=float, default=1.0)
    b.add_argument("--fade-out", dest="fade_out", type=float, default=2.0)
    b.add_argument("--duration", type=float)
    b.add_argument("--raw-range", dest="raw_range", action="store_true",
                   help="cuts 里的 start/end 是素材取用区间（默认当作屏上占用时长）")
    b.add_argument("-o", "--out", default="out/timeline.json")

    c = sub.add_parser("check")
    c.add_argument("path")

    a = ap.parse_args()
    if a.cmd == "build":
        sys.exit(cmd_build(a))
    sys.exit(0 if cmd_check(a.path) else 1)


if __name__ == "__main__":
    main()
