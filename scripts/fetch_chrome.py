#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 Remotion 准备 Chrome Headless Shell（国内网络专用）。

    python fetch_chrome.py --version 157.0.8080.0

Remotion 首次渲染会从 storage.googleapis.com 下载，国内经常 ECONNRESET。
这里改从 npmmirror 的 chrome-for-testing 镜像取，解到 templates/remotion/.chrome/，
render_remotion.py 会自动发现它。

不动系统、不装扩展，只往工程目录里放一个独立浏览器。
"""
import argparse
import os
import subprocess
import sys
import zipfile

MIRROR = "https://registry.npmmirror.com/-/binary/chrome-for-testing/%s/win64/chrome-headless-shell-win64.zip"
DEST = r"D:/workbuddy/runtime/chrome-headless-shell"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="157.0.8080.0")
    ap.add_argument("--dest", default=DEST)
    ap.add_argument("--keep-zip", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.dest, exist_ok=True)
    exe = os.path.join(a.dest, "chrome-headless-shell-win64", "chrome-headless-shell.exe")
    if os.path.exists(exe):
        print("已存在:", exe)
        return

    url = MIRROR % a.version
    zpath = os.path.join(a.dest, "chs.zip")
    print("下载", url)
    # 断点续传：镜像偶尔会掐连接，重试三次
    for attempt in range(3):
        r = subprocess.run(["curl", "-sSL", "-C", "-", "--max-time", "600",
                            "-o", zpath, url])
        if r.returncode == 0:
            break
        print("  第 %d 次中断，继续续传…" % (attempt + 1))

    if not os.path.exists(zpath) or os.path.getsize(zpath) < 100 * 1024 * 1024:
        sys.exit("下载不完整，重试或换 --version")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(a.dest)
    if not a.keep_zip:
        os.remove(zpath)
    print("解压完成:", exe)
    print("render_remotion.py 会自动使用它")


if __name__ == "__main__":
    main()
