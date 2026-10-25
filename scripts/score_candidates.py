#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按权重算候选分、标红线、给淘汰建议 —— 打分机制的算术部分。

    python scripts/score_candidates.py out/score.json --layer shot
    python scripts/score_candidates.py out/score.json --layer script --json

它只负责三件事：算加权分、查规则、排序。**判断由人做**——
脚本拦得住的是"权重加错、漏写证据、踩红线还打高分"这类硬错误。

score.json 结构见 references/02-scoring.md 第五节。
"""
import argparse
import json
import sys

WEIGHTS = {
    "style": {"mood": 0.30, "material": 0.20, "stability": 0.20,
              "distinct": 0.15, "rhythm": 0.15},
    "script": {"hook": 0.20, "lyrics": 0.20, "feasible": 0.15, "arc": 0.15,
               "purity": 0.10, "distinct": 0.10, "editable": 0.10},
    "shot": {"subject": 0.20, "feasible": 0.20, "lyrics": 0.15,
             "composition": 0.15, "light": 0.15, "contrast": 0.15},
    "douyin": {"hook": 0.25, "retention": 0.20, "lyrics": 0.15,
               "feasible": 0.15, "arc": 0.10, "interaction": 0.05,
               "series": 0.05, "editable": 0.05},
}

# 可生成性红线：命中就扣分（不是判死，但基本赢不了）
RED_LINES = {
    "hand_closeup": -1.5,
    "on_screen_text": -2.0,
    "many_people": -1.0,
    "precision_machine": -1.0,
    "reflection": -0.5,
    "complex_perspective": -0.5,
    "brand_ip": -2.0,
}

CN = {
    "mood": "情绪匹配", "material": "素材匹配", "stability": "出图稳定",
    "distinct": "差异化", "rhythm": "节奏契合",
    "hook": "钩子", "lyrics": "歌词咬合", "feasible": "可生成性",
    "arc": "情绪曲线", "purity": "风格纯度", "editable": "可剪辑性",
    "subject": "主体明确", "composition": "构图可读", "light": "光与色",
    "contrast": "前后对比", "retention": "留存曲线", "interaction": "互动",
    "series": "系列识别",
}


def score_one(cand, layer):
    w = WEIGHTS[layer]
    s = cand.get("scores") or {}
    missing = [k for k in w if k not in s]
    total = 0.0
    for k, wt in w.items():
        total += float(s.get(k, 0)) * wt
    red = cand.get("red_lines") or []
    pen = sum(RED_LINES.get(r, 0) for r in red)
    return total, total + pen, missing, pen


def check_layer(items, layer, name):
    """返回 (行列表, 问题列表)"""
    w = WEIGHTS[layer]
    rows, issues = [], []
    if abs(sum(w.values()) - 1.0) > 1e-6:
        issues.append("权重和不为 1（%.3f）" % sum(w.values()))

    for c in items:
        cid = c.get("id", "?")
        raw, final, missing, pen = score_one(c, layer)
        if c.get("score") is not None:
            final = float(c["score"])          # 手写分优先，脚本只做校验
        if missing:
            issues.append("%s/%s 缺维度：%s" % (name, cid, "、".join(CN.get(m, m) for m in missing)))
        if not (c.get("evidence") or "").strip():
            issues.append("%s/%s 没写证据（只给数字不算评过）" % (name, cid))
        if c.get("red_lines") and final >= 4.0:
            issues.append("%s/%s 踩了红线还给了 %.2f 分，复核一下" % (name, cid, final))
        if layer == "douyin":
            required = {
                "hook_evidence": "首帧钩子证据",
                "retention_beats": "留存变化点",
                "interaction_hook": "唯一评论问题",
                "series_marker": "系列识别物",
            }
            for key, label in required.items():
                if not c.get(key):
                    issues.append("%s/%s 缺少%s（%s）" % (name, cid, label, key))
            beats = c.get("retention_beats") or []
            if len(beats) < 4:
                issues.append("%s/%s 留存变化点少于 4 个" % (name, cid))
            if c.get("veto"):
                issues.append("%s/%s 命中抖音否决项：%s" % (name, cid, "、".join(c["veto"])))
        rows.append(dict(id=cid, raw=raw, final=final, pen=pen,
                         red=c.get("red_lines") or [], evidence=c.get("evidence", "")))

    if rows:
        vals = [r["final"] for r in rows]
        if min(vals) >= 4.9:
            issues.append("%s 全员接近满分 —— 这轮没在挑" % name)
        rows.sort(key=lambda r: -r["final"])
        for i, r in enumerate(rows):
            r["rank"] = i + 1
    return rows, issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("score_json")
    ap.add_argument("--layer", default="shot", choices=["style", "script", "shot", "douyin"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    data = json.load(open(a.score_json, encoding="utf-8"))
    out, issues = [], []

    if a.layer == "shot":
        for sh in data.get("shots", []):
            rows, iss = check_layer(sh.get("candidates", []), "shot", sh.get("id", "?"))
            for r in rows:
                r["shot"] = sh.get("id")
            out.extend(rows)
            issues.extend(iss)
        group_key = "shot"
    elif a.layer == "script":
        rows, iss = check_layer(data.get("script", {}).get("candidates", []), "script", "script")
        for r in rows:
            r["shot"] = "script"
        out.extend(rows)
        issues.extend(iss)
        group_key = "shot"
    elif a.layer == "douyin":
        rows, iss = check_layer(data.get("douyin", data.get("script", {})).get("candidates", []), "douyin", "douyin")
        for r in rows:
            r["shot"] = "douyin"
        out.extend(rows)
        issues.extend(iss)
        group_key = "shot"
    else:
        cands = data.get("style", {}).get("candidates", [])
        rows, iss = check_layer(cands, "style", "style")
        for r in rows:
            r["shot"] = "style"
        out.extend(rows)
        issues.extend(iss)
        group_key = "shot"

    if a.json:
        print(json.dumps(dict(rows=out, issues=issues), ensure_ascii=False, indent=1))
        return

    # 表格式输出：按组 + 排名
    last = None
    for r in sorted(out, key=lambda x: (x[group_key], x["rank"])):
        if r[group_key] != last:
            print("\n[%s]" % r[group_key])
            last = r[group_key]
        flag = " ← 建议采用" if r["rank"] == 1 else ""
        red = (" 红线:%s" % ",".join(r["red"])) if r["red"] else ""
        print("  %d. %-3s %5.2f   %s%s%s"
              % (r["rank"], r["id"], r["final"], r["evidence"][:46], red, flag))

    if issues:
        print("\n[问题 %d 条]" % len(issues))
        for i in issues:
            print("  ! " + i)
    else:
        print("\n[校验通过]")


if __name__ == "__main__":
    main()
