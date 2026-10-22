#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对齐的唯一算法内核 —— 所有入口（官方时间戳 / 歌词 / 已有 ASS）都走这里。

前端只有一套参数，不再有"生成期 250–3200Hz/10ms、修复期 250–4200Hz/4ms"两套：

    SR=16000  NFFT=512  HOP=64（4ms 步长）
    HPSS：频率方向中位 → 谐波（人声），压掉打击乐
    频带 250–4200Hz，log1p 压缩后取正向谱通量
    1.5s 滑动中位做局部归一（前奏与副歌的峰才可比）
    峰值阈值 0.10，最小间隔 45ms

调用：
    from align_core import analyze, align_line, char_error, WEIGHT
"""
import numpy as np

try:
    from retime_ass import onset_env, peaks_in, dp_align, novelty_at
except ImportError:                                    # 允许从别处 import
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from retime_ass import onset_env, peaks_in, dp_align, novelty_at

# 统一参数（改这里等于改全链路，别在调用方另写一套）
THR_PEAK = 0.10          # 取峰下限
THR_STRONG = 0.30        # "可辨认的人声起音"下限，逐字校对用它
SEP = 0.045              # 峰最小间隔 45ms
WIN_SHOW = 0.70          # 逐字只铺到整句的 70%
WIN_SCENE = 0.52         # 大词句
SEARCH = 0.60            # 句级位移搜索半径

WEIGHT = {"han": 1.0, "space": 1.4, "punct": 0.5}


def is_punct(ch):
    return ch in "，。、！？；：…—·「」『』（）《》,.!?;:'\"()"


def char_weights(text):
    """逐字权重：汉字 1.0、空格 1.4（换气）、标点 0.5。"""
    w = []
    for ch in text:
        if ch.strip() == "":
            w.append(WEIGHT["space"])
        elif is_punct(ch):
            w.append(WEIGHT["punct"])
        else:
            w.append(WEIGHT["han"])
    return np.array(w, dtype=np.float32)


def analyze(path):
    """音频 → (nov, t)。所有入口共用，且只能从这里拿。"""
    return onset_env(path)


def _expect(start, end, text, win):
    """按权重把字铺在 [start, start+win*(end-start)] 上。"""
    w = char_weights(text)
    total = float(w.sum()) or 1.0
    span = max(0.05, (end - start) * win)
    cum = np.concatenate([[0.0], np.cumsum(w)[:-1]])
    return start + cum / total * span, w


def align_line(nov, t, start, end, text, win=WIN_SHOW):
    """把一句歌词对到起音峰上，返回逐字时刻与质量信息。"""
    expect, _ = _expect(start, end, text, win)
    lo, hi = start - SEARCH, min(t[-1], end + SEARCH)
    pt, pf = peaks_in(nov, t, lo, hi, thr=THR_PEAK, sep=SEP)
    n = len(text)

    if len(pt) < n:
        return dict(times=list(expect), alt=list(expect), fit="uniform", delta=0.0,
                    reason="峰不足（%d<%d）" % (len(pt), n))

    pick = dp_align(pt, expect)
    if pick is None or len(pick) != n:
        # DP 合并了重复峰：退回均分，但标注出来
        return dict(times=list(expect), alt=list(expect), fit="uniform", delta=0.0,
                    reason="DP 退化（峰 %d / 字 %d）" % (len(pick) if pick is not None else 0, n))

    pick = np.sort(np.asarray(pick, dtype=np.float32))
    g = greedy_align(nov, t, expect)
    return dict(times=[float(x) for x in pick], alt=[float(x) for x in g],
                fit="dp", delta=float(pick[0] - start), reason="")


def dp_align2(pt, expect, lam=1.20, min_gap_ratio=0.45):
    """带最小间隔约束的 DP。

    原来的 dp_align 只惩罚"间隔偏离"，不禁止过近——实测会出现
    "三个字挤进 0.27s、下一字跳 0.78s"的塌缩。这里加两条硬约束：
      1. 相邻两字至少隔 max(0.12s, min_gap_ratio × 步长)
      2. 节奏偏离权重提到 1.20
    """
    N, M = len(expect), len(pt)
    if M < N:
        return None
    step = (expect[-1] - expect[0]) / max(1, N - 1) if N > 1 else 0.30
    gap = max(0.12, min_gap_ratio * step)
    INF = 1e9
    dp = np.full((N, M), INF)
    bk = np.zeros((N, M), dtype=int)
    dp[0] = np.abs(pt - expect[0])
    for k in range(1, N):
        for i in range(k, M):
            cand = np.full(M, INF, dtype=np.float32)
            ok = (pt[i] - pt[:i]) >= gap
            if not ok.any():
                continue
            prev = np.where(ok, dp[k - 1, :i], INF)
            cand[:i] = prev + lam * np.abs((pt[i] - pt[:i]) - step)
            j = int(np.argmin(cand))
            if cand[j] < INF:
                dp[k, i] = cand[j] + abs(pt[i] - expect[k])
                bk[k, i] = j
    i = int(np.argmin(dp[N - 1]))
    if dp[N - 1, i] >= INF:
        return None
    pick = [i]
    for k in range(N - 1, 0, -1):
        i = int(bk[k, i])
        pick.append(i)
    return pt[sorted(set(pick))]


def greedy_align(nov, t, expect):
    """第二套独立估计：逐字各取离期望最近的峰，强制单调。

    它和 DP 的差别，就是"这个字到底对在哪个音上"的不确定度。
    两种方法一致 → 可信；分歧大 → 该字必须人工听。
    """
    out, last = [], -9.0
    for e in expect:
        pt, _ = peaks_in(nov, t, max(last + 0.08, e - 0.45), e + 0.45, thr=THR_PEAK, sep=SEP)
        if len(pt) == 0:
            out.append(float(e))
            continue
        j = int(np.argmin(np.abs(pt - e)))
        out.append(float(pt[j]))
        last = float(pt[j])
    return out


def char_error(nov, t, times, alt=None, ref=None):
    """逐字校对：每个字和最近的"强起音"比。

    返回每字：err（秒，越大越可疑）、peak（该处起音强度）、weak（附近没有强起音）
    说明：没有真值音频时，"误差"只能对到可辨认的人声起音上——
    所以这里量的是**距最近强起音的偏差**，不是距"标准答案"的偏差。
    """
    out = []
    thr = THR_PEAK
    if ref:
        # 用本句实际取到的峰强度中位定"可信起音"的门槛：
        # 这首歌普通音节只有 0.15–0.25，用固定 0.30 会把正常字全判成错
        thr = max(THR_PEAK, 0.55 * float(np.median(ref)))
    for i, x in enumerate(times):
        peak = float(novelty_at(nov, t, [x], tol=0.045))
        strong, _ = peaks_in(nov, t, x - 0.45, x + 0.45, thr=thr, sep=SEP)
        e_s = float(np.min(np.abs(strong - x))) if len(strong) else None
        e_a = abs(float(x) - float(alt[i])) if (alt is not None and i < len(alt)) else None
        # 门槛只看"离最近可信起音多远"；两种方法的分歧单独报（口径不同，不能相加）
        out.append(dict(err=e_s, peak=peak, weak=(peak < THR_PEAK * 0.9),
                        err_peak=e_s, err_alt=e_a))
    return out


def grade(max_err, weak_ratio):
    """A/B/C 三级：A 可直接用，B 抽检，C 必须人工。"""
    if max_err is not None and max_err <= 0.15 and weak_ratio <= 0.10:
        return "A"
    if max_err is not None and max_err <= 0.30 and weak_ratio <= 0.25:
        return "B"
    return "C"
