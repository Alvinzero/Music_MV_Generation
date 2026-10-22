#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Remotion 的大依赖搬到 D 盘，C 盘只留目录联接（junction）。

    python relocate_deps.py            # 干跑，只报告会做什么
    python relocate_deps.py --apply    # 真搬

搬三样：
  templates/remotion/node_modules  →  D:/workbuddy/runtime/remotion-node_modules
  templates/remotion/.chrome       →  D:/workbuddy/runtime/chrome-headless-shell
  npm 缓存                          →  D:/workbuddy/runtime/npm-cache（npm config set cache）

搬完在工程目录建 NTFS junction，Node 的模块解析完全透明，`npx remotion` 照常用。
用 junction 不用 symlink：Windows 下 symlink 要管理员权限，junction 不要。
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(ROOT, "templates", "remotion")
RUNTIME = r"D:/workbuddy/runtime"

JOBS = [
    (os.path.join(PROJECT, "node_modules"),
     os.path.join(RUNTIME, "remotion-node_modules"), "node_modules"),
    (os.path.join(PROJECT, ".chrome"),
     os.path.join(RUNTIME, "chrome-headless-shell"), ".chrome"),
]


def is_junction(path):
    try:
        return os.path.islink(path) or bool(os.path.exists(path) and
                                           os.path.samefile(path, os.path.realpath(path)) is False)
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的搬（默认只干跑）")
    a = ap.parse_args()

    os.makedirs(RUNTIME, exist_ok=True)
    plan = []
    for src, dst, label in JOBS:
        if not os.path.exists(src):
            print("[跳过] %s 不存在（还没装？）" % label)
            continue
        if os.path.exists(dst) and os.path.isdir(dst) and os.path.exists(os.path.join(src, "..")):
            pass
        plan.append((src, dst, label))

    print("计划：")
    for src, dst, label in plan:
        print("  %-14s %s\n                 → %s" % (label, src, dst))
    print("  缓存            npm config set cache %s/npm-cache" % RUNTIME)

    if not a.apply:
        print("\n这是干跑。加 --apply 执行。")
        return

    for src, dst, label in plan:
        if os.path.exists(dst):
            sys.exit("目标已存在，先人工确认：%s" % dst)
        print("搬运", label, "…")
        shutil.move(src, dst)
        subprocess.run(["cmd", "/c", "mklink", "/J", src.replace("/", "\\"),
                        dst.replace("/", "\\")], check=True,
                       capture_output=True, text=True)
        print("  已建 junction:", src, "→", dst)

    subprocess.run(["cmd", "/c", "npm", "config", "set", "cache",
                    (RUNTIME + "/npm-cache").replace("/", "\\"), "--global"],
                   capture_output=True, text=True)
    print("npm 缓存 →", RUNTIME + "/npm-cache")
    print("\n完成。C 盘只剩 junction，实际文件都在 D 盘。")


if __name__ == "__main__":
    main()
