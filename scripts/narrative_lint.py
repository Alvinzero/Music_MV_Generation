#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抖音双轨分镜静态检查。

检查字段、单镜时长、首镜钩子、重复段升级、生产提示词与备选验收。
只检查规则是否遗漏，不判断画面是否好看。

用法：
  python narrative_lint.py shots.json
  python narrative_lint.py shots.json --production
  python narrative_lint.py shots.json --production --strict -o out/narrative_report.json
"""
import argparse
import json
import os
import sys

ROLES = {"hook", "world", "goal", "escalation", "turn", "payoff", "breath", "comment", "series"}
CHANGES = {"new_info", "new_relation", "new_consequence", "new_goal", "breath", "payoff"}
BASE_REQUIRED = ["traffic_role", "change_type", "visual", "camera", "continuity"]
PROD_REQUIRED = ["image_prompt", "motion_prompt", "negative", "backup_prompt", "acceptance"]


def load_shots(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("shots"), list):
            return data["shots"]
        if isinstance(data.get("video"), list):
            return data["video"]
    raise ValueError("JSON 必须是镜头数组、{shots:[...]} 或 timeline 的 {video:[...]}")


def sec(shot, key, fps):
    if key in shot and shot[key] is not None:
        return float(shot[key])
    if key == "start" and "start_sec" in shot:
        return float(shot["start_sec"])
    if key == "start" and "start_frame" in shot:
        return float(shot["start_frame"]) / fps
    if key == "end" and "end_sec" in shot:
        return float(shot["end_sec"])
    if key == "end" and "end_frame" in shot:
        return float(shot["end_frame"]) / fps
    return None


def duration(shot, fps):
    if "dur_sec" in shot:
        return float(shot["dur_sec"])
    a, b = sec(shot, "start", fps), sec(shot, "end", fps)
    if a is not None and b is not None:
        return b - a
    if "in_frame" in shot and "out_frame" in shot:
        speed = float(shot.get("speed", 1.0)) or 1.0
        return (shot["out_frame"] - shot["in_frame"]) / speed / fps
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shots_json")
    ap.add_argument("--production", action="store_true", help="额外检查生图/视频提示词、备选和验收")
    ap.add_argument("--strict", action="store_true", help="警告也按错误处理")
    ap.add_argument("--max-shot", type=float, default=6.04)
    ap.add_argument("-o", "--out", default="")
    a = ap.parse_args()

    try:
        shots = load_shots(a.shots_json)
    except Exception as e:
        print("输入错误:", e)
        return 1
    if not shots:
        print("输入错误: 没有镜头")
        return 1

    errors, warns = [], []
    for i, s in enumerate(shots):
        sid = str(s.get("id") or "s%02d" % (i + 1))
        for key in BASE_REQUIRED:
            if key not in s or s[key] in (None, "", []):
                errors.append(f"{sid}: 缺少必填字段 {key}")
        role = s.get("traffic_role")
        if role and role not in ROLES:
            errors.append(f"{sid}: 非法 traffic_role={role}")
        change = s.get("change_type")
        if change and change not in CHANGES:
            errors.append(f"{sid}: 非法 change_type={change}")
        dur = duration(s, 24)
        if dur is None:
            errors.append(f"{sid}: 无法计算镜头时长")
        elif dur <= 0:
            errors.append(f"{sid}: 镜头时长必须大于 0")
        elif dur > a.max_shot + 1e-6:
            errors.append(f"{sid}: {dur:.3f}s 超过单镜上限 {a.max_shot:.2f}s")
        if role in {"hook", "payoff", "comment"} and not s.get("audience_question"):
            errors.append(f"{sid}: {role} 必须填写 audience_question")
        if s.get("repeat_of") and not s.get("upgrade"):
            errors.append(f"{sid}: 有 repeat_of 但没有 upgrade，重复段不得纯重播")
        if a.production:
            for key in PROD_REQUIRED:
                if key not in s or s[key] in (None, "", []):
                    errors.append(f"{sid}: 生产模式缺少 {key}")
            neg = str(s.get("negative", "")).lower()
            for term in ("text", "watermark", "logo"):
                if term not in neg:
                    warns.append(f"{sid}: negative 建议包含 {term}")
            acc = s.get("acceptance")
            if isinstance(acc, list) and len(acc) < 2:
                warns.append(f"{sid}: acceptance 至少写 2 条")
            motion = str(s.get("motion_prompt", ""))
            if any(x in motion for x in ("提升留存", "爆款", "推流")):
                warns.append(f"{sid}: 推流词不应写进 motion_prompt，只写可生成的运动")

    first = shots[0]
    if first.get("traffic_role") != "hook":
        errors.append("首镜 traffic_role 必须是 hook")
    if len(shots) >= 8 and shots[-1].get("traffic_role") not in {"payoff", "comment", "series"}:
        warns.append("末镜缺少 payoff/comment/series 情绪落点")

    breath_run = 0.0
    for s in shots:
        dur = duration(s, 24) or 0.0
        if s.get("change_type") == "breath":
            breath_run += dur
            if breath_run > 25.0:
                warns.append("连续 breath 超过 25 秒，没有有效变化")
                breath_run = 0.0
        else:
            breath_run = 0.0

    if a.strict:
        errors.extend(warns)
        warns = []
    report = {
        "file": a.shots_json,
        "shots": len(shots),
        "production": a.production,
        "strict": a.strict,
        "errors": errors,
        "warnings": warns,
        "passed": not errors,
    }
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
