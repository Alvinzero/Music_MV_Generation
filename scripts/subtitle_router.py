#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按画面特征给十二套字幕配方打分 —— 让每部片得到自己的那一套，而不是"暗调就暖光字"。

    python scripts/subtitle_router.py --profile out/sub_profile.json
    python scripts/subtitle_router.py --demo            # 用内置样例跑一遍看输出长什么样

profile（八特征，全部必填）：
{
 "luma":     "dark | mid | bright | contrasty",
 "hue":      "warm | cool | neutral | neon",
 "material": "paper | cloth | metal | live | digital",
 "light":    "back | side | top | none",
 "density":  "sparse | dense",
 "motion":   "static | slowpush | handheld | fastcut",
 "era":      "modern | retro | oriental | future",
 "mood":     "warm | cold | sharp | sad"
}

输出：Top2 + 每套的命中/失配理由 + 该用哪个脚本。
参数细节见 references/05b-subtitle-recipes.md。
"""
import argparse
import json
import sys

WEIGHT = {"luma": 0.20, "material": 0.18, "mood": 0.16, "hue": 0.14,
          "light": 0.12, "density": 0.08, "motion": 0.06, "era": 0.06}

CN = {"luma": "明度", "material": "材质", "mood": "情绪", "hue": "主色",
      "light": "光向", "density": "密度", "motion": "运动", "era": "年代"}

# 每套配方：八个特征各自接受的取值
RECIPES = {
    "01-paper-card": dict(
        label="手账纸卡", carrier="纸卡", script="make_subs.py",
        fit={"luma": ["bright", "mid"], "hue": ["warm", "neutral"],
             "material": ["paper", "cloth"], "light": ["side"],
             "density": ["sparse"], "motion": ["static", "slowpush"],
             "era": ["modern", "retro"], "mood": ["warm"]}),
    "02-window-glow": dict(
        label="窗光透字", carrier="无", script="make_subs_glow.py",
        fit={"luma": ["dark", "contrasty"], "hue": ["warm"],
             "material": ["paper"], "light": ["back"],
             "density": ["sparse"], "motion": ["static", "slowpush"],
             "era": ["modern"], "mood": ["sad", "warm"]}),
    "03-stone-carve": dict(
        label="碑刻沉字", carrier="无", script="make_subs_glow.py",
        fit={"luma": ["mid", "dark"], "hue": ["cool", "neutral"],
             "material": ["live", "metal"], "light": ["side"],
             "density": ["dense"], "motion": ["static"],
             "era": ["retro"], "mood": ["cold", "sharp"]}),
    "04-neon-bleed": dict(
        label="霓虹溢光", carrier="无", script="make_subs_glow.py",
        fit={"luma": ["dark"], "hue": ["neon"],
             "material": ["metal", "live"], "light": ["none"],
             "density": ["dense"], "motion": ["handheld", "fastcut"],
             "era": ["modern", "future"], "mood": ["sharp"]}),
    "05-film-sub": dict(
        label="胶片字幕条", carrier="半透条", script="make_subs.py",
        fit={"luma": ["mid", "bright"], "hue": ["neutral", "cool"],
             "material": ["live"], "light": ["side", "top"],
             "density": ["dense"], "motion": ["handheld"],
             "era": ["modern"], "mood": ["cold"]}),
    "06-pencil-hand": dict(
        label="铅笔手写", carrier="无", script="make_subs_glow.py",
        fit={"luma": ["bright", "mid"], "hue": ["warm"],
             "material": ["paper", "cloth"], "light": ["side"],
             "density": ["sparse"], "motion": ["static", "slowpush"],
             "era": ["retro", "modern"], "mood": ["warm"]}),
    "07-metal-stamp": dict(
        label="金属压印", carrier="无", script="make_subs_glow.py",
        fit={"luma": ["mid"], "hue": ["cool"],
             "material": ["metal"], "light": ["top"],
             "density": ["dense"], "motion": ["static"],
             "era": ["future"], "mood": ["sharp"]}),
    "08-ink-colophon": dict(
        label="水墨题跋", carrier="无", script="make_subs_glow.py",
        fit={"luma": ["bright", "mid"], "hue": ["warm", "neutral"],
             "material": ["paper", "cloth"], "light": ["side"],
             "density": ["sparse"], "motion": ["static"],
             "era": ["oriental"], "mood": ["cold"]}),
    "09-collage-torn": dict(
        label="拼贴撕纸", carrier="多色纸卡", script="make_subs.py",
        fit={"luma": ["bright"], "hue": ["warm"],
             "material": ["paper", "cloth"], "light": ["side"],
             "density": ["sparse", "dense"], "motion": ["fastcut"],
             "era": ["retro"], "mood": ["warm"]}),
    "10-frosted-bar": dict(
        label="磨砂玻璃条", carrier="磨砂条", script="make_subs.py",
        fit={"luma": ["mid", "dark"], "hue": ["neutral", "cool"],
             "material": ["metal", "digital"], "light": ["none"],
             "density": ["dense"], "motion": ["static", "slowpush"],
             "era": ["future", "modern"], "mood": ["cold"]}),
    "11-spotlight": dict(
        label="追光舞台", carrier="光晕", script="make_subs_glow.py",
        fit={"luma": ["dark"], "hue": ["warm"],
             "material": ["live", "cloth"], "light": ["back"],
             "density": ["sparse"], "motion": ["handheld"],
             "era": ["modern"], "mood": ["warm", "sad"]}),
    "12-mono-data": dict(
        label="数据等宽", carrier="无", script="make_subs_glow.py",
        fit={"luma": ["dark", "contrasty"], "hue": ["cool"],
             "material": ["digital", "metal"], "light": ["none"],
             "density": ["dense"], "motion": ["static"],
             "era": ["future"], "mood": ["sharp", "cold"]}),
}

DEMO = {"luma": "dark", "hue": "warm", "material": "paper", "light": "back",
        "density": "sparse", "motion": "static", "era": "modern", "mood": "sad"}


def score(profile):
    rows = []
    for key, r in RECIPES.items():
        total, hit, miss = 0.0, [], []
        for f, w in WEIGHT.items():
            v = profile.get(f)
            ok = v in r["fit"].get(f, [])
            total += w if ok else 0.0
            (hit if ok else miss).append("%s=%s" % (CN[f], v))
        rows.append(dict(key=key, label=r["label"], carrier=r["carrier"],
                         script=r["script"], score=round(total * 5, 2),
                         hit=hit, miss=miss))
    rows.sort(key=lambda x: -x["score"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.demo:
        profile = DEMO
        print("（demo）画像：", json.dumps(profile, ensure_ascii=False))
    elif a.profile:
        profile = json.load(open(a.profile, encoding="utf-8"))
    else:
        sys.exit("给 --profile 或 --demo")

    missing = [CN[f] for f in WEIGHT if f not in profile]
    if missing:
        sys.exit("profile 缺字段：%s（八个特征都要填）" % "、".join(missing))

    rows = score(profile)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return

    print("\n%-24s %5s  %s" % ("配方", "匹配", "载体 / 脚本"))
    for r in rows:
        print("%-24s %5.2f  %s / %s" % (r["label"], r["score"], r["carrier"], r["script"]))

    top = rows[:2]
    print("\n[建议] 取 top2 各排一句样张给用户选：")
    for i, r in enumerate(top, 1):
        print("  %d) %s（%.2f）  命中 %d/8：%s"
              % (i, r["label"], r["score"], len(r["hit"]), "、".join(r["hit"][:5])))
        if r["miss"]:
            print("     失配：%s —— 这几项要和用户确认，或做定向微调"
                  % "、".join(r["miss"]))

    if top[0]["score"] - top[1]["score"] < 0.3:
        print("\n  ⚠ 前两名分差 <0.3，必须两张样张都出，让用户定。")
    gap = [f for f in WEIGHT if profile.get(f) not in RECIPES[top[0]["key"]]["fit"][f]]
    if gap:
        print("\n  微调建议：%s 与首选配方不完全匹配，按 05-subtitles.md 第三节第三步调参数。"
              % "、".join(CN[g] for g in gap))


if __name__ == "__main__":
    main()
