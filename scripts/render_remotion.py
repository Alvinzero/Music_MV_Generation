#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 timeline.json 渲染成片（Remotion 后端）。

    python render_remotion.py out/timeline.json -o out/final.mp4
    python render_remotion.py out/timeline.json --studio   # 只起 Studio 预览

做的事：
  1. 把素材软链/复制到 Remotion 工程的 public/
  2. 音频先过两遍 loudnorm（Remotion 自己不做响度标准化）
  3. 把 timeline.json 里的绝对路径改成 public 相对路径，写成 props
  4. npx remotion render

与 render_ffmpeg.py 输出同规格，可互相替换；出片后用 quality_check.py 验。
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


def find_npx():
    """Windows 上 npx 是 .cmd，subprocess 不认，必须取全路径。"""
    for name in (["npx.cmd", "npx"] if os.name == "nt" else ["npx"]):
        p = shutil.which(name)
        if p:
            return p
    return "npx.cmd" if os.name == "nt" else "npx"


NPX = find_npx()


def find_browser():
    """Remotion 首次渲染要从 storage.googleapis.com 下 Chrome Headless Shell，
    国内网络常常 ECONNRESET。直接用本机已有的 Edge / Chrome 更稳。"""
    for local in (r"D:/workbuddy/runtime/chrome-headless-shell/chrome-headless-shell-win64/chrome-headless-shell.exe",
                  os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "templates", "remotion", ".chrome",
                               "chrome-headless-shell-win64", "chrome-headless-shell.exe")):
        if os.path.exists(local):
            return local
    if os.name != "nt":
        return None
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(c):
            return c
    return None


def measure(path, I, TP, LRA):
    txt = subprocess.run(
        [FF, "-hide_banner", "-i", path, "-af",
         "loudnorm=I=%s:TP=%s:LRA=%s:print_format=json" % (I, TP, LRA),
         "-f", "null", "-"], capture_output=True, text=True, errors="ignore").stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", txt, re.S)
    return json.loads(m.group(0)) if m else None


def prepare_audio(src, dst, I, TP, LRA):
    meas = measure(src, I, TP, LRA)
    af = "loudnorm=I=%s:TP=%s:LRA=%s" % (I, TP, LRA)
    if meas:
        af += (":measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s"
               ":offset=%s:linear=true"
               % (meas["input_i"], meas["input_tp"], meas["input_lra"],
                  meas["input_thresh"], meas.get("target_offset", "0")))
        print("  两遍 loudnorm：源 %s LUFS / %s dBTP" % (meas["input_i"], meas["input_tp"]))
    subprocess.run([FF, "-y", "-v", "error", "-i", src, "-af", af + ",aresample=48000",
                    "-c:a", "aac", "-b:a", "192k", dst], check=True)


def normalize_color(path, crf):
    """Remotion 出的是 yuvj420p(全范围)；统一成 yuv420p + bt709，
    这样与 ffmpeg 后端出片颜色一致，换后端不会偏色。"""
    tmp = path + ".norm.mp4"
    print("色彩归一化 → yuv420p / bt709")
    r = subprocess.run([FF, "-y", "-v", "error", "-i", path,
                        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                        "-pix_fmt", "yuv420p",
                        "-colorspace", "bt709", "-color_primaries", "bt709",
                        "-color_trc", "bt709", "-c:a", "copy",
                        "-movflags", "+faststart", tmp])
    if r.returncode == 0 and os.path.exists(tmp):
        os.replace(tmp, path)
    else:
        print("  [注意] 归一化失败，保留原始输出（颜色可能与其他后端略有差异）")
        if os.path.exists(tmp):
            os.remove(tmp)


def link_into_public(src, public):
    """优先硬链接，失败则复制。文件名冲突时加前缀。"""
    os.makedirs(public, exist_ok=True)
    base = os.path.basename(src)
    dst = os.path.join(public, base)
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
        return base
    if os.path.exists(dst):
        stem, ext = os.path.splitext(base)
        dst = os.path.join(public, stem + "_2" + ext)
        base = os.path.basename(dst)
    try:
        os.link(src, dst)
    except Exception:
        shutil.copyfile(src, dst)
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("-o", "--out", default="out/final.mp4")
    ap.add_argument("--project", default=None,
                    help="Remotion 工程目录，默认用本 skill 的 templates/remotion")
    ap.add_argument("--lufs", type=float, default=-14.0)
    ap.add_argument("--tp", type=float, default=-1.5)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--studio", action="store_true", help="只起 Studio，不渲染")
    ap.add_argument("--no-normalize", dest="no_normalize", action="store_true",
                    help="跳过渲染后的像素格式/色彩归一化")
    ap.add_argument("--browser", default=None,
                    help="指定浏览器可执行文件；默认自动找本机 Edge/Chrome")
    ap.add_argument("--keep-public", action="store_true")
    a = ap.parse_args()

    tl = json.load(open(a.timeline, encoding="utf-8"))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project = os.path.abspath(a.project or os.path.join(here, "templates", "remotion"))
    if not os.path.isdir(project):
        sys.exit("找不到 Remotion 工程: %s" % project)
    if not os.path.isdir(os.path.join(project, "node_modules")):
        sys.exit("工程还没装依赖：cd \"%s\" && npm install" % project)
    public = os.path.join(project, "public")
    os.makedirs(public, exist_ok=True)
    os.makedirs(os.path.join(public, "fonts"), exist_ok=True)

    # 字体
    src_fonts = os.path.join(here, "assets", "fonts")
    if os.path.isdir(src_fonts):
        for f in os.listdir(src_fonts):
            if f.lower().endswith((".ttf", ".otf")):
                shutil.copyfile(os.path.join(src_fonts, f),
                                os.path.join(public, "fonts", f))

    # 视频素材
    print("准备素材 →", public)
    for seg in tl["video"]:
        seg["file"] = link_into_public(seg["file"], public)

    # 音频
    music = (tl.get("audio") or {}).get("music")
    if music:
        out_audio = os.path.join(public, "audio.m4a")
        print("音频标准化 →", out_audio)
        prepare_audio(music, out_audio, a.lufs, a.tp,
                      (tl["audio"].get("loudnorm") or {}).get("LRA", 11))
        tl["audio"]["music"] = "audio.m4a"
    tl["audio"] = tl.get("audio") or {}
    tl["audio"].pop("voice", None)

    props = os.path.join(project, "props.json")
    json.dump({"timeline": tl}, open(props, "w", encoding="utf-8"),
              ensure_ascii=False)

    cmd = [NPX, "remotion"]
    if a.studio:
        cmd += ["studio"]
    else:
        out_abs = os.path.abspath(a.out)
        os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
        cmd += ["render", "Film", out_abs,
                "--props=" + props, "--codec=h264", "--crf=%d" % a.crf,
                "--concurrency=%d" % a.concurrency,
                "--overwrite"]
        if a.browser:
            cmd.append("--browser-executable=%s" % a.browser)
    if a.browser is None:
        a.browser = find_browser()
        if a.browser:
            print("使用本机浏览器:", a.browser)
    print("运行:", " ".join(cmd))
    r = subprocess.run(cmd, cwd=project)
    if r.returncode != 0:
        sys.exit("Remotion 渲染失败（退出码 %d）" % r.returncode)
    if not a.studio:
        if not a.no_normalize:
            normalize_color(a.out, a.crf)
        print("完成 →", a.out, "(%.0f MB)" % (os.path.getsize(a.out) / 1048576))


if __name__ == "__main__":
    main()
