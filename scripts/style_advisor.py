#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""听歌 + 读歌词 → 推荐 3 套动画风格。

用户只需要提供：歌名、歌词文本、音乐 mp3。
脚本分析 tempo / 能量 / 明亮度 / 歌词意象，给出带理由的 3 个候选。

用法:
    python style_advisor.py --audio song.mp3 --title "把回忆拼好给你" --lyrics lyrics.txt
    python style_advisor.py --audio song.mp3 --lyrics lyrics.txt --json style.json
    python style_advisor.py --pick papercut          # 输出该风格的锁定参数

输出（--pick 之外）：候选风格 + 打分 + 理由 + 建议节奏参数。
"""

import argparse
import json
import os
import re
import subprocess
import sys

import numpy as np

SR = 22050
HOP = 512
NFFT = 2048

# ---- 风格元数据（与 references/style-library.md 对应）----
STYLES = {
    "papercut": dict(
        name="纸雕拼贴", bpm=(62, 96), density=(2.0, 5.0), bright=(0.25, 0.66),
        motifs=["回忆", "照片", "拼", "收", "藏", "烟花", "海", "夜", "雨", "旧", "窗", "灯"],
        shot=(4.0, 6.0), fade=0.5, cost=1.0,
        why="分层撕纸和拼图正好承载「收集／拼合」这类动作",
        sub="一字一纸片方块，米色纸面 + 纸边，逐字弹出"),
    "clay": dict(
        name="黏土定格", bpm=(80, 118), density=(3.2, 6.5), bright=(0.35, 0.75),
        motifs=["抱", "笑", "玩", "糖", "孩子", "牵", "捏", "暖", "陪"],
        shot=(3.5, 5.0), fade=0.35, cost=1.1,
        why="体积感强，适合有肢体动作、情绪外放的段落",
        sub="粘土块状字，圆体 + 厚描边 + 内阴影"),
    "gouache": dict(
        name="水粉绘本", bpm=(58, 92), density=(1.6, 4.0), bright=(0.3, 0.7),
        motifs=["雨", "风", "云", "花", "叶", "海", "夏", "秋", "黄昏", "远方", "山", "河"],
        shot=(5.0, 7.0), fade=0.9, cost=0.9,
        why="笔触柔和，适合自然意象多、情绪内敛的歌",
        sub="手写体，无底框，深色细描边直接压在画面上"),
    "ink": dict(
        name="水墨留白", bpm=(52, 82), density=(1.0, 3.2), bright=(0.15, 0.5),
        motifs=["离", "别", "忘", "念", "梦", "月", "江", "雪", "空", "远", "故人", "归"],
        shot=(6.0, 8.0), fade=1.0, cost=0.8,
        why="极慢的歌配留白最有力，镜头可以长到 8 秒",
        sub="毛笔字，无底框，竖排或左对齐"),
    "felt": dict(
        name="羊毛毡布偶", bpm=(66, 100), density=(1.8, 4.6), bright=(0.3, 0.68),
        motifs=["家", "暖", "抱", "睡", "梦", "妈妈", "童年", "毛", "小", "安"],
        shot=(4.5, 6.5), fade=0.6, cost=1.1,
        why="毛绒质感天然带治愈感，适合私密、安心的段落",
        sub="布片缝线字，布面色块 + 虚线描边"),
    "flatvector": dict(
        name="扁平矢量", bpm=(96, 150), density=(5.0, 9.0), bright=(0.45, 0.9),
        motifs=["街", "城", "车", "跑", "跳", "现在", "一起", "冲", "舞台", "光"],
        shot=(2.0, 3.5), fade=0.25, cost=0.85,
        why="节奏快、切口多，扁平色块在硬切下最清晰",
        sub="无衬线粗体块，整行滑入"),
    "glass": dict(
        name="彩绘玻璃", bpm=(70, 120), density=(3.8, 7.8), bright=(0.35, 0.85),
        motifs=["光", "燃", "命运", "永远", "天", "神", "誓言", "闪耀", "绽放", "炽热"],
        shot=(3.0, 5.0), fade=0.45, cost=1.0,
        why="透光与浓色适合副歌爆发的能量，视觉冲击强",
        sub="铅条描边字，像玻璃拼片"),
    "retroprint": dict(
        name="复古丝网", bpm=(84, 130), density=(3.6, 7.4), bright=(0.3, 0.72),
        motifs=["那年", "旧", "照片", "青春", "校", "信", "磁带", "夏天", "从前", "告白"],
        shot=(3.0, 4.5), fade=0.3, cost=0.9,
        why="网点与套色错位天然带年代感，适合青春回忆",
        sub="粗体套色字，主色 + 偏移的第二色"),
}


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def load_mono(path):
    cmd = [ffmpeg_exe(), "-v", "error", "-i", path,
           "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def analyse_audio(path):
    y = load_mono(path)
    if len(y) < SR:
        raise SystemExit("音频太短")
    n = 1 + (len(y) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = y[idx] * np.hanning(NFFT)[None, :]
    spec = np.abs(np.fft.rfft(frames, axis=1))

    # 能量（RMS，归一到 0-1，用 95 分位做上限避免个别爆点拉满）
    rms = np.sqrt((frames ** 2).mean(axis=1))
    energy = float(np.clip(np.percentile(rms, 90) / (rms.max() + 1e-9), 0, 1))

    # 明亮度（频谱质心 / 奈奎斯特）
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    cent = (spec * freqs[None, :]).sum(axis=1) / (spec.sum(axis=1) + 1e-9)
    bright = float(np.clip(np.median(cent) / (SR / 2), 0, 1))

    # onset 密度 → 每秒钟有多少个能量突跳
    flux = np.diff(np.log1p(spec * 10.0), axis=0)
    flux[flux < 0] = 0
    env = flux.sum(axis=1)
    env = env / (env.max() + 1e-9)
    thr = 0.25
    peaks = 0
    last = -999
    for i, v in enumerate(env):
        if v > thr and i - last > 3:
            peaks += 1
            last = i
    dur = len(y) / SR
    density = peaks / dur

    # BPM（自相关）
    fps = SR / HOP
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac[:1] = 0
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)
    hi = min(hi, len(ac) - 1)
    lag = lo + int(np.argmax(ac[lo:hi])) if hi > lo else int(fps * 60 / 90)
    bpm = 60.0 * fps / lag

    return dict(bpm=round(bpm, 1), energy=round(energy, 3), bright=round(bright, 3),
                density=round(density, 2), duration=round(dur, 2))


def analyse_lyrics(text):
    text = re.sub(r"\s+", "", text or "")
    hits = {}
    for sid, st in STYLES.items():
        c = sum(text.count(m) for m in st["motifs"])
        hits[sid] = c
    # 意象分类
    cats = {
        "自然": ["雨", "雪", "风", "海", "云", "月", "星", "花", "叶", "山", "河", "浪", "天空"],
        "时间": ["夏", "冬", "春", "秋", "夜", "黄昏", "清晨", "年", "旧", "从前", "回忆"],
        "情感": ["爱", "想", "哭", "笑", "忘", "等", "陪", "离开", "告别", "思念", "抱"],
        "场景": ["街", "房", "窗", "灯", "车", "楼", "城", "校", "天台", "海边"],
        "物件": ["照片", "信", "糖", "伞", "烟花", "汽水", "风铃", "磁带", "盆栽"],
    }
    found = {k: [w for w in ws if w in text] for k, ws in cats.items()}
    return hits, {k: v for k, v in found.items() if v}


def score(feat, hits, sid):
    st = STYLES[sid]

    def range_score(v, lo, hi, pad):
        if lo <= v <= hi:
            return 1.0
        d = lo - v if v < lo else v - hi
        return max(0.0, 1.0 - d / pad)

    s_bpm = range_score(feat["bpm"], st["bpm"][0], st["bpm"][1], 40)
    s_den = range_score(feat["density"], st["density"][0], st["density"][1], 2.5)
    s_bri = range_score(feat["bright"], st["bright"][0], st["bright"][1], 0.35)
    s_mot = min(1.0, hits.get(sid, 0) / 4.0)
    total = 0.30 * s_bpm + 0.22 * s_den + 0.13 * s_bri + 0.35 * s_mot
    return round(total, 3), dict(bpm=round(s_bpm, 2), density=round(s_den, 2),
                                 bright=round(s_bri, 2), motif=round(s_mot, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--lyrics", default="", help="歌词文本文件路径")
    ap.add_argument("--title", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--pick", default="", help="输出该风格的锁定参数")
    a = ap.parse_args()

    if a.pick:
        sid = a.pick
        if sid not in STYLES:
            raise SystemExit("未知风格: %s\n可选: %s" % (sid, ", ".join(STYLES)))
        st = STYLES[sid]
        lock = dict(style=sid, name=st["name"], shot=st["shot"], fade=st["fade"],
                    cost=st["cost"], subtitle=st["sub"], why=st["why"])
        print(json.dumps(lock, ensure_ascii=False, indent=1))
        return

    text = ""
    if a.lyrics and os.path.isfile(a.lyrics):
        with open(a.lyrics, encoding="utf-8") as f:
            text = f.read()
    elif a.lyrics:
        text = a.lyrics

    feat = analyse_audio(a.audio)
    hits, cats = analyse_lyrics(text)
    ranked = sorted(((sid,) + score(feat, hits, sid) for sid in STYLES),
                    key=lambda x: -x[1])

    print("=" * 56)
    if a.title:
        print("歌曲：%s" % a.title)
    print("时长 %.1fs  BPM %.1f  响度 %.2f  明亮度 %.2f  发音点密度 %.2f/s"
          % (feat["duration"], feat["bpm"], feat["energy"], feat["bright"], feat["density"]))
    if cats:
        print("歌词意象：" + "；".join("%s %s" % (k, "/".join(v)) for k, v in cats.items()))
    print("=" * 56)
    for i, (sid, sc, det) in enumerate(ranked[:3], 1):
        st = STYLES[sid]
        print("\n【%d】%s  （契合度 %.2f）" % (i, st["name"], sc))
        print("    为什么适合：%s" % st["why"])
        print("    建议节奏：单镜 %.0f–%.0f 秒，叠化 %.2fs" % (st["shot"][0], st["shot"][1], st["fade"]))
        print("    字幕样式：%s" % st["sub"])
        print("    成本系数：%.2f" % st["cost"])
        print("    各项：速度 %.2f 密度 %.2f 明亮 %.2f 意象 %.2f"
              % (det["bpm"], det["density"], det["bright"], det["motif"]))
    print("\n选定后运行： python style_advisor.py --pick <id>")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(dict(features=feat, motifs=cats,
                           ranking=[dict(style=s, score=sc, detail=d) for s, sc, d in ranked]),
                      f, ensure_ascii=False, indent=1)
        print("已写入:", a.json)


if __name__ == "__main__":
    main()
