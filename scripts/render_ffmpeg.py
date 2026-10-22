#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 timeline.json 渲染成片（ffmpeg 后端）。

    python render_ffmpeg.py out/timeline.json -o out/final.mp4
    python render_ffmpeg.py out/timeline.json --subs out/subs.ass --fonts assets/fonts
    python render_ffmpeg.py out/timeline.json --delogo 3:7:142:66 --dry-run

要点：
  * 每个输入都加 -threads 1。输入超过 ~20 个时不加会报 get_buffer() failed。
  * xfade 的 offset = 下一个镜头的 start_frame（左轨时间 == 成片时间）。
  * trim 用 start_frame/end_frame 做帧级裁剪，不靠秒，避免累积误差。
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


def esc_ass_path(p, fonts_dir):
    """ass 滤镜里的路径：正斜杠 + 转义盘符冒号。"""
    p = os.path.abspath(p).replace("\\", "/")
    out = "ass='%s'" % p.replace(":", "\\:")
    if fonts_dir:
        fd = os.path.abspath(fonts_dir).replace("\\", "/")
        out += ":fontsdir='%s'" % fd.replace(":", "\\:")
    return out


def build_filter(tl, args):
    fps = tl["canvas"]["fps"]
    W, H = tl["canvas"]["width"], tl["canvas"]["height"]
    segs = tl["video"]
    n = len(segs)
    lines = []
    seg_frames = [int(round((s["out_frame"] - s["in_frame"])
                            / (float(s.get("speed", 1.0)) or 1.0))) for s in segs]

    for i, s in enumerate(segs):
        pre = []
        if args.delogo:
            x, y, w, h = [int(v) for v in args.delogo.split(":")]
            pre.append("delogo=x=%d:y=%d:w=%d:h=%d" % (x, y, w, h))
        # 统一画布：不足补边、超出缩放
        pre.append("scale=%d:%d:force_original_aspect_ratio=decrease" % (W, H))
        pre.append("pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black" % (W, H))
        chain = ",".join(pre)
        sp = float(s.get("speed", 1.0)) or 1.0
        pts = "PTS-STARTPTS" if abs(sp - 1.0) < 1e-6 else "(PTS-STARTPTS)/%.6f" % sp
        lines.append(
            "[%d:v]%s,trim=start_frame=%d:end_frame=%d,setpts=%s,"
            "fps=%s,format=yuv420p,settb=AVTB[v%d]"
            % (i, chain, s["in_frame"], s["out_frame"], pts, fps, i + 1))

    prev = "v1"
    for i in range(1, n):
        xf = segs[i].get("xfade") or {}
        f = int(xf.get("frames", 0))
        typ = xf.get("type", "fade")
        off = segs[i]["start_frame"] / float(fps)
        out = "[vout]" if i == n - 1 else "[x%d]" % i
        if f > 0:
            if f >= min(seg_frames[i - 1], seg_frames[i]):
                sys.exit("叠化帧数 %d 超过相邻镜头长度，检查 timeline" % f)
            lines.append("[%s][v%d]xfade=transition=%s:duration=%.6f:offset=%.6f%s"
                         % (prev, i + 1, typ, f / float(fps), off, out))
        else:
            lines.append("[%s][v%d]concat=n=2:v=1:a=0%s" % (prev, i + 1, out))
        prev = out.strip("[]")

    tail = []
    if args.subs:
        tail.append(esc_ass_path(args.subs, args.fonts))
    if args.eq:
        tail.append(args.eq)
    if args.vignette:
        tail.append("vignette=a=%s" % args.vignette)
    dur = tl["duration_frames"] / float(fps)
    fi, fo = tl["audio"].get("fade_in_sec", 0) or 0, tl["audio"].get("fade_out_sec", 0) or 0
    if args.fade and fi > 0:
        tail.append("fade=t=in:st=0:d=%.3f" % fi)
    if args.fade and fo > 0:
        tail.append("fade=t=out:st=%.3f:d=%.3f" % (max(0.1, dur - fo), fo))
    tail.append("tpad=stop_mode=clone:stop_duration=1")
    tail.append("format=yuv420p")
    lines.append("[%s]%s[v]" % (prev, ",".join(tail)))
    return ";\n".join(lines)


def measure_loudness(path, I=-14.0, TP=-1.0, LRA=11.0):
    """单遍 loudnorm 打不准（实测 -14 只能到 -12）。先测一遍拿 measured_* 再套用。"""
    txt = subprocess.run(
        [FF, "-hide_banner", "-i", path, "-af",
         "loudnorm=I=%s:TP=%s:LRA=%s:print_format=json" % (I, TP, LRA),
         "-f", "null", "-"], capture_output=True, text=True, errors="ignore").stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def build_audio(tl, args, idx_music, idx_voice):
    dur = tl["duration_frames"] / float(tl["canvas"]["fps"])
    parts = []
    if idx_voice is not None:
        parts.append("[%d:a]aresample=44100,volume=%sdB[vo]" % (idx_voice, args.voice_gain))
    if idx_music is not None:
        ln = tl["audio"].get("loudnorm") or {}
        I, TP, LRA = ln.get("I", -14), ln.get("TP", -1.0), ln.get("LRA", 11)
        extra = ""
        if not args.loudnorm_one_pass:
            mus = tl["audio"]["music"]
            meas = measure_loudness(mus, I, TP, LRA)
            if meas and "input_i" in meas:
                extra = (":measured_I=%s:measured_TP=%s:measured_LRA=%s"
                         ":measured_thresh=%s:offset=%s:linear=true"
                         % (meas["input_i"], meas["input_tp"], meas["input_lra"],
                            meas["input_thresh"], meas.get("target_offset", "0")))
                print("  两遍 loudnorm：实测 %s LUFS / %s dBTP"
                      % (meas["input_i"], meas["input_tp"]))
            else:
                print("  [注意] 响度测量失败，退回单遍 loudnorm（可能达不到目标）")
        parts.append(
            "[%d:a]loudnorm=I=%s:TP=%s:LRA=%s%s,aresample=44100,volume=%sdB[mu]"
            % (idx_music, I, TP, LRA, extra, args.music_gain))
    if idx_voice is not None and idx_music is not None:
        parts.append("[mu]volume=0.35[mu2]")
        parts.append("[vo][mu2]amix=inputs=2:duration=first:dropout_transition=0[am]")
    elif idx_music is not None:
        parts.append("[mu]anull[am]")
    else:
        parts.append("[vo]anull[am]")
    fi = tl["audio"].get("fade_in_sec", 0) or 0
    fo = tl["audio"].get("fade_out_sec", 0) or 0
    parts.append("[am]atrim=0:%.3f,asetpts=PTS-STARTPTS,"
                 "afade=t=in:st=0:d=%.3f,afade=t=out:st=%.3f:d=%.3f[a]"
                 % (dur, fi, max(0.1, dur - fo), fo))
    return ";\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("-o", "--out", default="out/final.mp4")
    ap.add_argument("--subs")
    ap.add_argument("--fonts", default=None)
    ap.add_argument("--delogo", help="x:y:w:h，去掉平台角标")
    ap.add_argument("--eq", default="", help="例如 contrast=1.03:saturation=1.04")
    ap.add_argument("--vignette", default="")
    ap.add_argument("--music-gain", dest="music_gain", type=float, default=0.0)
    ap.add_argument("--voice-gain", dest="voice_gain", type=float, default=0.0)
    ap.add_argument("--no-fade", dest="fade", action="store_false")
    ap.add_argument("--loudnorm-one-pass", dest="loudnorm_one_pass",
                    action="store_true", help="单遍 loudnorm（快但通常差 1–2 LU）")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="slow")
    ap.add_argument("--dry-run", action="store_true", help="只写 filter 脚本不渲染")
    ap.add_argument("--filter-out", default="out/filter_render.txt")
    a = ap.parse_args()

    tl = json.load(open(a.timeline, encoding="utf-8"))
    segs = tl["video"]
    inputs, args_list = [], []
    for s in segs:
        inputs.append((s["file"], True))
    music = (tl.get("audio") or {}).get("music")
    voice = (tl.get("audio") or {}).get("voice")
    idx_music = idx_voice = None
    if music:
        idx_music = len(inputs)
        inputs.append((music, False))
    if voice:
        idx_voice = len(inputs)
        inputs.append((voice, False))

    for p, is_video in inputs:
        if not os.path.exists(p):
            sys.exit("输入不存在: %s" % p)
        if is_video and len(inputs) > 20:
            args_list += ["-threads", "1"]
        args_list += ["-i", p]

    vf = build_filter(tl, a)
    af = build_audio(tl, a, idx_music, idx_voice)
    script = vf + ";\n" + af

    os.makedirs(os.path.dirname(a.filter_out) or ".", exist_ok=True)
    open(a.filter_out, "w", encoding="utf-8").write(script + "\n")

    dur = tl["duration_frames"] / float(tl["canvas"]["fps"])
    print("镜头 %d，输入 %d，总长 %.3fs" % (len(segs), len(inputs), dur))
    print("filter → %s" % a.filter_out)

    cmd = [FF, "-y", "-hide_banner", "-loglevel", "warning"] + args_list + [
        "-filter_complex_script", a.filter_out,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", a.preset, "-crf", str(a.crf),
        "-pix_fmt", "yuv420p", "-r", str(tl["canvas"]["fps"]),
        "-c:a", "aac", "-b:a", "192k",
        "-t", "%.3f" % dur, "-movflags", "+faststart", a.out]
    if len(inputs) > 20:
        cmd = cmd[:3] + ["-filter_complex_threads", "2"] + cmd[3:]

    if a.dry_run:
        print(" ".join(cmd))
        return
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit("渲染失败，看 out/filter_render.txt 里的滤镜脚本")
    print("完成 →", a.out, "(%.0f MB)" % (os.path.getsize(a.out) / 1048576))


if __name__ == "__main__":
    main()
