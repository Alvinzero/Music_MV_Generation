#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行级起音校正 + 逐字铺开窗口：把"字幕总慢半拍"这两件事一次修掉。

问题拆开看是两层：

  1. **行级**：LRC/歌词表给的起点，常比真实起唱晚 0.05–0.4s。
     整句都跟着晚，观众第一感知就是"字幕延迟"。
  2. **句内**：把整句时长平均分给每个字，长句尾部往往是间奏，
     最后一个字要等到 95% 才亮 —— 越唱越晚。

本脚本对每个句子的**起点**做一次实测校正，并给出该句该用多大的
"逐字铺开窗口"（只铺到整句的百分之多少）。

用法:
    python fit_lines.py --audio song.m4a --lines out/lines.json -o out/lines_fit.json
    python fit_lines.py --audio song.m4a --lines out/lines.json --scene 11,18,39
    python fit_lines.py --audio song.m4a --lines out/lines.json --dry     # 只看诊断

输出每句新增：
    delta      行级校正量（秒，负=提前）
    start_fit  start + delta
    win        逐字铺开比例（0.52 大词句 / 0.70 普通句）

为什么不用另外两种看起来很合理的做法（都实测过，都会错）：
  · 取谱通量最大峰 → 常锁在鼓点/镲片上，得到"中位 +0.03s"，看不出偏晚。
  · 找"第一个能量下陷"当句尾 → 连音和换气会被当成句尾，一半句子钳在搜索边界上。
"""

import argparse
import json
import subprocess

import numpy as np

SR, NFFT, HOP = 22050, 1024, 220          # hop 10ms


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def load_band(path, lo, hi):
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", path, "-f", "f32le",
                          "-ac", "1", "-ar", str(SR), "-"], capture_output=True).stdout
    y = np.frombuffer(raw, dtype=np.float32)
    win = np.hanning(NFFT).astype(np.float32)
    n = 1 + (len(y) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    S = np.abs(np.fft.rfft(y[idx] * win, axis=1))
    f = np.fft.rfftfreq(NFFT, 1 / SR)
    S = S[:, (f > lo) & (f < hi)]
    e = 20 * np.log10(np.sqrt((S ** 2).mean(axis=1)) + 1e-9)
    e = np.convolve(e, np.ones(3) / 3, mode="same")
    t = np.arange(len(e)) * HOP / SR
    return t, e


def detect_onset(t, e, s, back, ahead, rise_db, hold_db):
    """在 [s-back, s+ahead] 里找真正的起唱：能量陡升且随后维持住。"""
    lo, hi = int(np.searchsorted(t, s - back)), int(np.searchsorted(t, s + ahead))
    for k in range(lo + 6, max(lo + 7, hi - 14)):
        if e[k + 3] - e[k - 3] > rise_db and e[k + 14] - e[k - 3] > hold_db:
            return float(t[k])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--lines", required=True, help="lines.json：[{start,end,text}]")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--band", default="400:1600", help="人声第一共振峰带，默认 400:1600")
    ap.add_argument("--back", type=float, default=0.45, help="往前搜多久（秒）")
    ap.add_argument("--ahead", type=float, default=0.35, help="往后搜多久（秒）")
    ap.add_argument("--rise", type=float, default=6.0, help="起音判定：20ms 上升 dB")
    ap.add_argument("--hold", type=float, default=3.0, help="起音后 140ms 仍高出 dB")
    ap.add_argument("--clamp", default="-0.36:0.05", help="校正量上下限（秒）")
    ap.add_argument("--default-shift", type=float, default=-0.08,
                    help="未检出起音的句子用这个默认前移")
    ap.add_argument("--window", type=float, default=0.70, help="普通句逐字铺开比例")
    ap.add_argument("--scene-window", type=float, default=0.52, help="大词句逐字铺开比例")
    ap.add_argument("--scene", default="", help="大词句下标，1-based，逗号分隔")
    ap.add_argument("--dry", action="store_true", help="只打印诊断，不写文件")
    a = ap.parse_args()

    lo, hi = (float(x) for x in a.band.split(":"))
    cmin, cmax = (float(x) for x in a.clamp.split(":"))
    scene = {int(x) - 1 for x in a.scene.split(",") if x.strip()}

    lines = json.load(open(a.lines, encoding="utf-8"))
    t, e = load_band(a.audio, lo, hi)

    deltas = []
    for i, ln in enumerate(lines):
        onset = detect_onset(t, e, ln["start"], a.back, a.ahead, a.rise, a.hold)
        if onset is None:
            d = a.default_shift
            ok = False
        else:
            d = max(cmin, min(cmax, onset - ln["start"]))
            ok = True
            deltas.append(d)
        ln["delta"] = round(d, 3)
        ln["start_fit"] = round(ln["start"] + d, 3)
        ln["win"] = a.scene_window if i in scene else a.window
        ln["onset_ok"] = ok

    det = np.array(deltas) if deltas else np.array([0.0])
    print(f"检出 {len(deltas)}/{len(lines)} 句有明确起音")
    if deltas:
        print(f"行级校正 中位 {np.median(det):+.3f}s  均值 {det.mean():+.3f}s  "
              f"最大前移 {det.min():+.3f}s")
    worst = sorted([l for l in lines if l["onset_ok"]], key=lambda x: x["delta"])[:5]
    if worst:
        print("前移最多的 5 句：")
        for l in worst:
            print(f"  {l['start']:7.2f} → {l['start_fit']:7.2f}  ({l['delta']:+.3f}s)  {l['text']}")

    if a.dry:
        return
    out = a.out or a.lines.replace(".json", "_fit.json")
    json.dump(lines, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→", out)


if __name__ == "__main__":
    main()
