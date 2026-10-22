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
import unicodedata
import sys

import numpy as np

SR = 22050
HOP = 512
NFFT = 2048

# ---- 风格元数据（与 references/style-library.md 对应）----
STYLES = {
    # ---------- 家族一 · 手作 ----------
    "papercut": dict(
        name="纸雕拼贴", family="手作", bpm=(62, 96), density=(2.0, 5.0), bright=(0.25, 0.66),
        motifs=["回忆", "照片", "拼", "收", "藏", "烟花", "海", "夜", "雨", "旧", "窗", "灯"],
        shot=(4.0, 6.0), fade=0.5, cost=1.0,
        why="分层撕纸和拼图正好承载「收集／拼合」这类动作",
        sub="一字一纸片方块，米色纸面 + 纸边，逐字弹出"),
    "clay": dict(
        name="黏土定格", family="手作", bpm=(80, 118), density=(3.2, 6.5), bright=(0.35, 0.75),
        motifs=["抱", "笑", "玩", "糖", "孩子", "牵", "捏", "暖", "陪"],
        shot=(3.5, 5.0), fade=0.35, cost=1.1,
        why="体积感强，适合有肢体动作、情绪外放的段落",
        sub="粘土块状字，圆体 + 厚描边 + 内阴影"),
    "felt": dict(
        name="羊毛毡布偶", family="手作", bpm=(66, 100), density=(1.8, 4.6), bright=(0.3, 0.68),
        motifs=["家", "暖", "抱", "睡", "梦", "妈妈", "童年", "毛", "小", "安"],
        shot=(4.5, 6.5), fade=0.6, cost=1.1,
        why="毛绒质感天然带治愈感，适合私密、安心的段落",
        sub="布片缝线字，布面色块 + 虚线描边"),
    "glass": dict(
        name="彩绘玻璃", family="手作", bpm=(70, 120), density=(3.8, 7.8), bright=(0.35, 0.85),
        motifs=["光", "燃", "命运", "永远", "天", "神", "誓言", "闪耀", "绽放", "炽热"],
        shot=(3.0, 5.0), fade=0.45, cost=1.0,
        why="透光与浓色适合副歌爆发的能量，视觉冲击强",
        sub="铅条描边字，像玻璃拼片"),

    # ---------- 家族二 · 绘画与版画 ----------
    "gouache": dict(
        name="水粉绘本", family="绘画", bpm=(58, 92), density=(1.6, 4.0), bright=(0.3, 0.7),
        motifs=["雨", "风", "云", "花", "叶", "海", "夏", "秋", "黄昏", "远方", "山", "河"],
        shot=(5.0, 7.0), fade=0.9, cost=0.9,
        why="笔触柔和，适合自然意象多、情绪内敛的歌",
        sub="手写体，无底框，深色细描边直接压在画面上"),
    "ink": dict(
        name="水墨留白", family="水墨东方", bpm=(52, 82), density=(1.0, 3.2), bright=(0.15, 0.5),
        motifs=["离", "别", "忘", "念", "梦", "月", "江", "雪", "空", "远", "故人", "归"],
        shot=(6.0, 8.0), fade=1.0, cost=0.8,
        why="极慢的歌配留白最有力，镜头可以长到 8 秒",
        sub="毛笔字，无底框，竖排或左对齐"),
    "oil": dict(
        name="古典油画", family="绘画", bpm=(50, 80), density=(1.2, 3.4), bright=(0.15, 0.45),
        motifs=["命运", "神", "永恒", "血", "罪", "祷", "王", "葬", "誓", "深渊", "死", "圣"],
        shot=(6.0, 8.0), fade=0.85, cost=1.05,
        why="明暗对照天然承载「宿命／沉重」，慢段最有分量",
        sub="衬线体，米白，无底框，字距略松"),
    "ukiyoe": dict(
        name="浮世绘木版", family="版画", bpm=(70, 105), density=(2.4, 5.2), bright=(0.35, 0.7),
        motifs=["海", "浪", "山", "桥", "雪", "舟", "街", "花", "风", "雨", "江", "渡"],
        shot=(4.0, 6.0), fade=0.55, cost=0.95,
        why="平涂加墨线适合横向叙事，像展开一幅长卷",
        sub="竖排仿宋，右下角配一枚朱红小印"),
    "gongbi": dict(
        name="工笔重彩", family="水墨东方", bpm=(55, 85), density=(1.4, 3.6), bright=(0.3, 0.6),
        motifs=["花", "鸟", "月", "亭", "灯", "扇", "绢", "荷", "香", "画", "帘", "钗"],
        shot=(5.0, 7.0), fade=0.9, cost=1.05,
        why="细线设色的精微感适合古风与器物细节",
        sub="仿宋细体，深墨色，竖排优先"),
    "woodcut": dict(
        name="黑白木刻", family="版画", bpm=(85, 130), density=(3.8, 7.6), bright=(0.18, 0.5),
        motifs=["喊", "痛", "砸", "挣", "断", "杀", "反抗", "血", "荒", "铁", "碎", "烧"],
        shot=(2.5, 4.0), fade=0.3, cost=0.85,
        why="刀痕与高反差适合爆发的重音句，视觉最硬",
        sub="粗黑体，反白色块压在画面上"),

    # ---------- 家族三 · 摄影与电影 ----------
    "cinematic": dict(
        name="电影写实", family="电影", bpm=(60, 100), density=(1.8, 4.4), bright=(0.25, 0.6),
        motifs=["路", "窗", "站台", "背影", "门", "走", "等", "车", "夜", "灯", "房", "手"],
        shot=(5.0, 7.0), fade=0.6, cost=1.2,
        why="真实质感让叙事落地，慢镜像正片而不是插画",
        sub="小字号白字 + 极轻投影，靠下居中"),
    "filmic16": dict(
        name="日系胶片", family="摄影", bpm=(70, 110), density=(2.2, 5.0), bright=(0.45, 0.8),
        motifs=["夏", "校", "操场", "单车", "阳光", "那年", "初恋", "走廊", "同学", "白衬衫", "蝉"],
        shot=(4.0, 6.0), fade=0.5, cost=1.15,
        why="过曝与逆光把「青春期」直接写在画面上",
        sub="细黑体白字，无底框，轻描边"),
    "noir": dict(
        name="黑白黑色电影", family="电影", bpm=(55, 90), density=(1.6, 4.0), bright=(0.1, 0.35),
        motifs=["离开", "背叛", "谎", "恨", "黑", "影", "烟", "午夜", "真相", "忘", "错", "罪"],
        shot=(5.0, 7.0), fade=0.7, cost=1.1,
        why="硬光与深黑适合对峙式的独白，情绪最冷",
        sub="白色无衬线，硬边，不描边不加底"),
    "neonoir": dict(
        name="赛博霓虹", family="电影", bpm=(90, 140), density=(4.0, 8.2), bright=(0.3, 0.7),
        motifs=["夜", "霓虹", "雨", "城", "孤独", "电", "机器", "街", "末", "信号", "闪", "光"],
        shot=(3.0, 5.0), fade=0.4, cost=1.25,
        why="湿地面反霓虹，都市夜行与电子感一步到位",
        sub="细字 + 发光描边，模拟霓虹灯管"),
    "cyanotype": dict(
        name="蓝晒", family="摄影", bpm=(55, 90), density=(1.2, 3.4), bright=(0.2, 0.5),
        motifs=["梦", "记", "忘", "旧", "影", "忆", "沉", "静", "蓝", "水", "叶", "远"],
        shot=(6.0, 8.0), fade=1.0, cost=0.9,
        why="单色蓝像褪色的记忆负片，极慢段落最合适",
        sub="细衬线白字，低不透明度，像被晒淡"),

    # ---------- 家族四 · 3D ----------
    "lowpoly": dict(
        name="低多边形 3D", family="3D", bpm=(85, 130), density=(3.4, 7.0), bright=(0.4, 0.8),
        motifs=["空", "远", "路", "光", "线", "几何", "山", "海", "未来", "静", "网", "方"],
        shot=(3.0, 5.0), fade=0.45, cost=1.0,
        why="面数与平直着色的疏离感，适合电子与氛围",
        sub="无衬线，几何感，压左下角"),
    "isometric": dict(
        name="等距微缩", family="3D", bpm=(75, 115), density=(2.8, 6.0), bright=(0.4, 0.75),
        motifs=["城", "房", "街", "楼", "窗", "家", "店", "路", "日常", "地图", "桌", "屋"],
        shot=(3.0, 5.0), fade=0.5, cost=1.0,
        why="沙盘式俯瞰把「一段日常」装进一个盒子里",
        sub="无衬线小字，与等距轴对齐"),

    # ---------- 家族五 · 图形设计 ----------
    "flatvector": dict(
        name="扁平矢量", family="图形设计", bpm=(96, 150), density=(5.0, 9.0), bright=(0.45, 0.9),
        motifs=["街", "城", "车", "跑", "跳", "现在", "一起", "冲", "舞台", "光"],
        shot=(2.0, 3.5), fade=0.25, cost=0.85,
        why="节奏快、切口多，扁平色块在硬切下最清晰",
        sub="无衬线粗体块，整行滑入"),
    "retroprint": dict(
        name="复古丝网", family="图形设计", bpm=(84, 130), density=(3.6, 7.4), bright=(0.3, 0.72),
        motifs=["那年", "旧", "照片", "青春", "校", "信", "磁带", "夏天", "从前", "告白"],
        shot=(3.0, 4.5), fade=0.3, cost=0.9,
        why="网点与套色错位天然带年代感，适合青春回忆",
        sub="粗体套色字，主色 + 偏移的第二色"),
    "bauhaus": dict(
        name="包豪斯几何", family="图形设计", bpm=(100, 150), density=(5.2, 9.5), bright=(0.5, 0.92),
        motifs=["形", "色", "构", "线", "圆", "方", "现代", "秩序", "设计", "节拍", "格", "块"],
        shot=(2.0, 3.0), fade=0.2, cost=0.85,
        why="纯构成语言配强节拍最利落，不讲故事只讲节奏",
        sub="无衬线粗体，配纯色块底"),

    # ---------- 家族 2 · 绘画（补充） ----------
    "pastel": dict(
        name="干粉彩", family="绘画", bpm=(60, 95), density=(1.6, 4.0), bright=(0.35, 0.72),
        motifs=["童年", "手写", "信", "画", "小", "记得", "从前", "偷偷", "纸条", "蜡笔"],
        shot=(4.0, 6.0), fade=0.7, cost=0.9,
        why="粉笔质感天然带「小时候」的手拙感，适合私密独白",
        sub="粉笔手写体，压画面，边缘带粉屑"),

    # ---------- 家族 3 · 版画（补充） ----------
    "risograph": dict(
        name="Riso 孔版", family="版画", bpm=(85, 130), density=(3.6, 7.4), bright=(0.45, 0.85),
        motifs=["街", "潮", "青春", "一起", "跑", "现在", "店", "海报", "夜", "玩"],
        shot=(3.0, 4.5), fade=0.3, cost=0.9,
        why="荧光专色加错版，是当下独立音乐最常用的印刷语言",
        sub="荧光双色套印，故意错开 2px"),

    # ---------- 家族 4 · 水墨东方（补充） ----------
    "mural": dict(
        name="壁画", family="水墨东方", bpm=(52, 85), density=(1.4, 3.6), bright=(0.25, 0.55),
        motifs=["古", "远", "轮回", "传说", "梦", "敦煌", "仙", "佛", "山", "壁", "千", "旧"],
        shot=(5.0, 7.0), fade=0.9, cost=1.0,
        why="剥落的土壁与矿物色自带千年时间感，宿命题材最有分量",
        sub="隶书或魏碑，赭红，压在壁面上"),

    # ---------- 家族 5 · 摄影（补充） ----------
    "polaroid": dict(
        name="宝丽来", family="摄影", bpm=(70, 105), density=(2.2, 5.0), bright=(0.4, 0.75),
        motifs=["记得", "那天", "拍", "照", "你", "我们", "瞬间", "留", "笑", "手"],
        shot=(3.0, 5.0), fade=0.35, cost=1.0,
        why="白边与直打闪光，把「随手记下来」的仓促感直接做进画面",
        sub="马克笔手写，压在照片下沿的白边上"),

    # ---------- 家族 7 · 3D（补充） ----------
    "voxel": dict(
        name="体素", family="3D", bpm=(95, 140), density=(4.2, 8.0), bright=(0.45, 0.82),
        motifs=["玩", "关", "通", "格", "方块", "像素", "城", "跑", "跳", "级"],
        shot=(2.5, 4.0), fade=0.3, cost=0.9,
        why="方块构成容错高，播放起来有游戏的通关感",
        sub="点阵或无衬线小字，压角标"),

    # ---------- 家族 9 · 动画 ----------
    "anime": dict(
        name="日式赛璐璐", family="动画", bpm=(80, 125), density=(3.0, 6.5), bright=(0.45, 0.82),
        motifs=["天空", "夏", "放学", "教室", "走廊", "喜欢", "等", "雨", "风", "少年", "少女", "回家"],
        shot=(3.0, 5.0), fade=0.4, cost=1.05,
        why="赛璐璐平涂配厚涂背景，是讲成长故事最省力的语言",
        sub="圆体 + 白描边，放在画面下方安全区"),
    "comic": dict(
        name="美式漫画", family="动画", bpm=(90, 135), density=(4.0, 8.0), bright=(0.35, 0.72),
        motifs=["打", "冲", "胜负", "街头", "态度", "喊", "你", "我", "现在", "燃", "拼"],
        shot=(2.5, 4.0), fade=0.25, cost=0.9,
        why="粗墨线加网点，适合态度强硬、句子短的段落",
        sub="旁白框或爆炸框，粗描边"),
    "pixelart": dict(
        name="像素", family="动画", bpm=(100, 150), density=(5.0, 9.0), bright=(0.4, 0.8),
        motifs=["游戏", "关", "币", "跳", "跑", "级", "像素", "电", "8bit", "街机", "通关"],
        shot=(2.0, 3.0), fade=0.2, cost=0.85,
        why="像素点本身就是年代符号，快歌段落最轻快",
        sub="点阵字，字重要够，小字号会糊"),

    # ---------- 家族 10 · 科幻与幻想（题材） ----------
    "scifi": dict(
        name="硬科幻", family="科幻幻想", bpm=(60, 105), density=(2.0, 5.0), bright=(0.5, 0.9),
        motifs=["未来", "机器", "信号", "星", "舱", "系统", "距离", "孤", "光", "数据", "末"],
        shot=(4.0, 6.0), fade=0.6, cost=1.2,
        why="冷白工程感提供「未来」的可信度，默认走电影写实介质",
        sub="极简无衬线，HUD 风（细线框 + 等宽数字）"),
    "steampunk": dict(
        name="蒸汽朋克", family="科幻幻想", bpm=(75, 115), density=(3.0, 6.0), bright=(0.3, 0.6),
        motifs=["齿轮", "机械", "铜", "蒸汽", "工", "时", "钟", "飞", "船", "旧", "造"],
        shot=(4.0, 6.0), fade=0.55, cost=1.2,
        why="黄铜与雾气把「工匠式浪漫」具象化，适合冒险叙事",
        sub="铸铁路牌字（窄体 + 铆钉边）"),
    "fantasy": dict(
        name="奇幻史诗", family="科幻幻想", bpm=(60, 100), density=(2.2, 5.0), bright=(0.35, 0.7),
        motifs=["远方", "传说", "王", "剑", "山", "云", "光", "永恒", "誓", "神", "归", "征"],
        shot=(5.0, 7.0), fade=0.8, cost=1.25,
        why="巨物与圣光负责副歌的体量感，靠轮廓识别角色",
        sub="古典衬线，金色细描边"),
}


FAMILY_ORDER = ["手作", "绘画", "版画", "水墨东方", "摄影", "电影", "3D", "图形设计", "动画", "科幻幻想"]


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


def pad_cjk(s, width):
    """按显示宽度补空格（中文算 2 列），否则 --list 的列会歪。"""
    n = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
    return s + " " * max(0, width - n)


def fold_bpm(b, lo=70.0, hi=155.0):
    """把速度按八度折进 [lo, hi) —— 92 与 184 是同一个"拍感"，不该判成两种歌。
    hi 取 155（略高于 flatvector 上限 150），保证快歌不被误折半。"""
    if b <= 0:
        return b
    while b < lo:
        b *= 2.0
    while b >= hi:
        b /= 2.0
    return b


def detect_bpm(env, fps):
    """自相关取峰 + 抛物线插值 + 八度归一。

    只取全区间 argmax 会踩两个坑：峰值落在搜索边界（倍频鬼影），
    以及八分音符脉冲比主拍更强导致报 2x。所以先取所有局部峰，
    每个峰折进 [70,140) 后按原始相关强度排序。
    """
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac[:1] = 0
    lags = np.arange(len(ac))
    acn = ac / np.maximum(len(e) - lags, 1)      # 按重叠长度归一，否则长 lag 天然吃亏
    acn[0] = 0

    lo = max(2, int(fps * 60 / 240))             # 240 BPM 上限
    hi = min(len(acn) - 2, int(fps * 60 / 40))   # 40 BPM 下限
    seg = acn[lo:hi + 1]
    peaks = [i for i in range(1, len(seg) - 1)
             if seg[i] > seg[i - 1] and seg[i] >= seg[i + 1]]
    if not peaks:
        peaks = [int(np.argmax(seg))]

    best_bpm, best_score, best_raw = None, -1.0, None
    for i in peaks:
        a, b, c = seg[i - 1], seg[i], seg[i + 1]
        den = a - 2 * b + c
        shift = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
        shift = float(np.clip(shift, -0.5, 0.5))   # 亚帧插值，避免整帧量化
        raw = 60.0 * fps / (lo + i + shift)
        if seg[i] > best_score:
            best_bpm, best_score, best_raw = fold_bpm(raw), seg[i], raw
    return round(best_bpm, 1), round(best_raw, 1)


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

    # BPM（自相关 + 八度归一）
    fps = SR / HOP
    bpm, bpm_raw = detect_bpm(env, fps)

    return dict(bpm=bpm, bpm_raw=bpm_raw,
                energy=round(energy, 3), bright=round(bright, 3),
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


def bpm_score(v, lo, hi, pad):
    """八度等价的区间打分：92 和 184 对"单手拍"来说是同一件事。

    取 1x / 0.5x / 2x 三个候选里最贴近该风格区间的一个，
    这样快歌仍会偏向 flatvector（96–150），慢歌仍偏向 ink（52–82）。
    """
    best = 0.0
    for k in (1.0, 0.5, 2.0):
        vv = v * k
        if lo <= vv <= hi:
            return 1.0
        d = lo - vv if vv < lo else vv - hi
        best = max(best, max(0.0, 1.0 - d / pad))
    return best


def score(feat, hits, sid):
    st = STYLES[sid]

    def range_score(v, lo, hi, pad):
        if lo <= v <= hi:
            return 1.0
        d = lo - v if v < lo else v - hi
        return max(0.0, 1.0 - d / pad)

    s_bpm = bpm_score(feat.get("bpm_raw", feat["bpm"]), st["bpm"][0], st["bpm"][1], 40)
    s_den = range_score(feat["density"], st["density"][0], st["density"][1], 2.5)
    s_bri = range_score(feat["bright"], st["bright"][0], st["bright"][1], 0.35)
    s_mot = min(1.0, hits.get(sid, 0) / 4.0)
    total = 0.30 * s_bpm + 0.22 * s_den + 0.13 * s_bri + 0.35 * s_mot
    return round(total, 3), dict(bpm=round(s_bpm, 2), density=round(s_den, 2),
                                 bright=round(s_bri, 2), motif=round(s_mot, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default="")
    ap.add_argument("--lyrics", default="", help="歌词文本文件路径")
    ap.add_argument("--title", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--pick", default="", help="输出该风格的锁定参数")
    ap.add_argument("--list", action="store_true", help="列出全部风格（按家族）")
    a = ap.parse_args()

    if a.list:
        for fam in FAMILY_ORDER:
            rows = [(sid, st) for sid, st in STYLES.items() if st.get("family") == fam]
            print("\n【%s】%d 套" % (fam, len(rows)))
            for sid, st in rows:
                print("  %-11s %s 单镜 %.1f–%.1fs 叠化 %.2f 成本 %.2f"
                      % (sid, pad_cjk(st["name"], 13), st["shot"][0], st["shot"][1],
                         st["fade"], st["cost"]))
        print("\n共 %d 套。锁定某套： python style_advisor.py --pick <id>" % len(STYLES))
        return

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

    if not a.audio:
        raise SystemExit("需要 --audio <音乐文件>；只想取某套风格的锁定参数请用 --pick <id>")

    feat = analyse_audio(a.audio)
    hits, cats = analyse_lyrics(text)
    ranked = sorted(((sid,) + score(feat, hits, sid) for sid in STYLES),
                    key=lambda x: -x[1])

    # 候选必须跨家族：同一家族最多 2 个，避免给出三套都是手作
    top, fam_n = [], {}
    for row in ranked:
        fam = STYLES[row[0]].get("family", "")
        if fam_n.get(fam, 0) >= 2:
            continue
        top.append(row)
        fam_n[fam] = fam_n.get(fam, 0) + 1
        if len(top) == 3:
            break
    if len(top) < 3:
        for row in ranked:
            if row[0] not in [t[0] for t in top]:
                top.append(row)
                if len(top) == 3:
                    break

    print("=" * 56)
    if a.title:
        print("歌曲：%s" % a.title)
    bpm_tag = ""
    raw = feat.get("bpm_raw") or feat["bpm"]
    if abs(raw - feat["bpm"]) > 0.5 and raw > 0:
        factor = feat["bpm"] / raw
        if factor >= 1.5:
            bpm_tag = "（原始检出 %.1f，已 ×%.0f 归一）" % (raw, factor)
        else:
            bpm_tag = "（原始检出 %.1f，已 ÷%.0f 归一）" % (raw, 1.0 / factor)
    print("时长 %.1fs  BPM %.1f%s  响度 %.2f  明亮度 %.2f  发音点密度 %.2f/s"
          % (feat["duration"], feat["bpm"], bpm_tag,
             feat["energy"], feat["bright"], feat["density"]))
    if cats:
        print("歌词意象：" + "；".join("%s %s" % (k, "/".join(v)) for k, v in cats.items()))
    print("=" * 56)
    for i, (sid, sc, det) in enumerate(top, 1):
        st = STYLES[sid]
        print("\n【%d】%s · %s  （契合度 %.2f）" % (i, st["name"], st.get("family", ""), sc))
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
