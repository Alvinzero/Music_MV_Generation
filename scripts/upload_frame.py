#!/usr/bin/env python3
"""首帧图床客户端：把本地图片传给 18080 的 HTTP 上传通道，打印公网 URL。

只用 Python 标准库，不需要 paramiko、不需要 SSH。
成功时 stdout **只输出一行 URL**，可直接被 media_api.py 的上传钩子捕获；
失败时原因写 stderr，并以非零码退出。

Token 读取顺序（命中即停，一般不需要写进命令行）：
  1. --token <value>
  2. 环境变量 MEDIA_UPLOAD_TOKEN
  3. 环境变量 MEDIA_UPLOAD_TOKEN_FILE 指向的文件
  4. ~/.media_upload_token（Windows 为 %USERPROFILE%\\.media_upload_token）
  5. 本脚本同目录的 .media_upload_token

用法：
  python upload_frame.py --file first-frame.png
  python upload_frame.py --file first-frame.png --dry-run     # 只看要发什么，不真传
  python upload_frame.py --check                             # 只查 Token 是否就位
  python upload_frame.py --usage                             # 只读查图床占用（不删任何文件）

退出码：2 参数/Token 缺失，3 上传被拒，4 服务器回传 sha256 与本地不一致，
5 查询占用时超过告警阈值（仅在给了 --warn-mb 或 MEDIA_FRAMES_WARN_MB 时）。
"""

import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_UPLOAD_URL = "http://152.136.41.242:18080/upload"
MAX_BYTES = 16 * 1024 * 1024
MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def die(msg, code=3):
    sys.stderr.write(msg.rstrip() + "\n")
    sys.exit(code)


def sniff_content_type(raw):
    for magic, mime in MAGIC:
        if raw.startswith(magic):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_token(cli_token):
    if cli_token:
        return cli_token.strip()
    env = os.environ.get("MEDIA_UPLOAD_TOKEN")
    if env and env.strip():
        return env.strip()
    token_file = os.environ.get("MEDIA_UPLOAD_TOKEN_FILE")
    candidates = []
    if token_file:
        candidates.append(token_file)
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    candidates.append(os.path.join(home, ".media_upload_token"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".media_upload_token"))
    for path in candidates:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                value = fh.read().strip()
            if value:
                return value
    return None


def upload(url, token, raw, content_type, timeout):
    req = urllib.request.Request(url, data=raw, method="POST")
    req.add_header("X-Upload-Token", token)
    req.add_header("Content-Type", content_type)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        die("网络错误：%s\n检查 18080 是否放通、服务器是否在线。" % exc, 3)


def usage_endpoint(upload_url):
    base = upload_url.rstrip("/")
    if base.endswith("/upload"):
        return base + "/usage"
    return base + "/upload/usage"


def fmt_time(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError):
        return "?"


def report_usage(upload_url, token, timeout, warn_mb):
    """只读查询图床占用，不做任何删除。"""
    url = usage_endpoint(upload_url)
    req = urllib.request.Request(url, method="GET")
    req.add_header("X-Upload-Token", token)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        die("查询占用失败 HTTP %s\n%s" % (exc.code, exc.read().decode("utf-8", "replace")[:400]), 3)
    except (urllib.error.URLError, TimeoutError) as exc:
        die("网络错误：%s" % exc, 3)
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        die("返回不是 JSON：%s" % body[:300], 3)

    total = float(data.get("bytes") or 0)
    buckets = data.get("age_buckets") or {}
    sys.stderr.write("目录 %s\n" % data.get("dir", "?"))
    sys.stderr.write("共 %s 个文件，占用 %.1f MiB；半成品(.uploading-*) %s 个\n"
                     % (data.get("files", 0), total / 1048576.0, data.get("stale_tmp", 0)))
    for key, label in (("lt_1d", "<1 天"), ("1_to_7d", "1-7 天"),
                       ("7_to_30d", "7-30 天"), ("gt_30d", ">30 天")):
        pair = buckets.get(key) or [0, 0]
        sys.stderr.write("  %-9s %4s 个  %7.1f MiB\n" % (label, pair[0], float(pair[1] or 0) / 1048576.0))
    sys.stderr.write("最早 %s / 最新 %s\n"
                     % (fmt_time(data.get("oldest_mtime")), fmt_time(data.get("newest_mtime"))))
    sys.stderr.write("只读快照，未删除任何文件；清理在服务器上跑 prune_frames.py\n")

    print(json.dumps({k: data.get(k) for k in
                      ("dir", "files", "bytes", "stale_tmp", "oldest_mtime", "newest_mtime")},
                     ensure_ascii=False, sort_keys=True))

    threshold = warn_mb
    if threshold is None and os.environ.get("MEDIA_FRAMES_WARN_MB"):
        try:
            threshold = float(os.environ["MEDIA_FRAMES_WARN_MB"])
        except ValueError:
            threshold = None
    if threshold is not None and total > threshold * 1048576.0:
        sys.stderr.write("已超过告警线 %.0f MiB，该清理了（先去服务器出清单，确认后再 --apply）。\n" % threshold)
        sys.exit(5)


def compress_to_jpeg(raw, quality, name="", max_side=None):
    """把图片压成 JPEG（可同时降尺寸）。图床公网带宽很低（实测峰值 ~3.7 Mbps，
    最坏 36 KB/s 且会抖到超时），上游拉取大图容易判失败，压缩能把体积降到约 1/5。

    返回 (bytes, content_type)。Pillow 缺失或压完反而更大时，原样返回。
    """
    try:
        from PIL import Image
    except ImportError:
        sys.stderr.write("提示：未安装 Pillow，跳过压缩（pip install pillow 可启用）\n")
        return raw, sniff_content_type(raw)
    try:
        buf = io.BytesIO()
        with Image.open(io.BytesIO(raw)) as im:
            if im.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                rgba = im.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            if max_side and max(im.size) > int(max_side):
                w, h = im.size
                scale = float(max_side) / max(w, h)
                im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
            im.save(buf, "JPEG", quality=int(quality), optimize=True, subsampling=0)
        out = buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("提示：压缩失败（%s），按原图上传\n" % exc)
        return raw, sniff_content_type(raw)
    if len(out) >= len(raw) and not max_side:
        return raw, sniff_content_type(raw)
    sys.stderr.write("压缩 %s: %.2f MB → %.2f MB (q%d%s, 省 %.0f%%)\n"
                     % (name, len(raw) / 1048576.0, len(out) / 1048576.0, int(quality),
                        ", 长边 %d" % int(max_side) if max_side else "",
                        (1 - len(out) / float(len(raw))) * 100))
    return out, "image/jpeg"


def main():
    ap = argparse.ArgumentParser(description="把首帧图片上传到图床，stdout 输出公网 URL")
    ap.add_argument("--file", required=False, help="本地图片路径（PNG/JPEG/WEBP，≤16 MiB）")
    ap.add_argument("--token", default=None, help="上传 Token；不给则按顺序查环境变量与 token 文件")
    ap.add_argument("--url", default=None, help="上传接口地址，默认 " + DEFAULT_UPLOAD_URL)
    ap.add_argument("--timeout", type=float, default=None,
                    help="单次上传超时秒数，默认 120（图床公网出口慢，别设太小）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要发送的请求信息，不上传")
    ap.add_argument("--check", action="store_true", help="只检查 Token 是否就位，不上传")
    ap.add_argument("--usage", action="store_true", help="只读查询图床占用快照，不删任何文件")
    ap.add_argument("--warn-mb", type=float, default=None,
                    help="配合 --usage：占用超过该 MiB 数时退出码 5（默认读 MEDIA_FRAMES_WARN_MB）")
    ap.add_argument("--jpeg-quality", type=int, default=None,
                    help="上传前压成 JPEG，取值 1-100（推荐 92）。图床带宽低，压缩能显著降低上游拉图超时。"
                         "默认读 MEDIA_UPLOAD_JPEG_QUALITY，都不给则原样上传")
    ap.add_argument("--max-side", type=int, default=None,
                    help="配合压缩：把长边缩到该像素（推荐 1440）。图床最坏带宽 36 KB/s 时，"
                         "长边 1440 约 7 秒可被上游拉完，1920 要 11 秒以上")
    args = ap.parse_args()

    upload_url = args.url or os.environ.get("MEDIA_UPLOAD_URL") or DEFAULT_UPLOAD_URL
    try:
        timeout = args.timeout if args.timeout is not None else float(os.environ.get("MEDIA_UPLOAD_TIMEOUT") or 120)
    except ValueError:
        die("MEDIA_UPLOAD_TIMEOUT 不是数字", 2)

    token = read_token(args.token)
    if args.check:
        if token:
            sys.stderr.write("Token 已就位（长度 %d，尾号 %s），接口 %s\n" % (len(token), token[-4:], upload_url))
            return
        die("没找到 Token。设置环境变量 MEDIA_UPLOAD_TOKEN，或写入 %USERPROFILE%\\.media_upload_token", 2)
    if not token:
        die("没找到上传 Token。三种办法：\n"
            "  1) 设环境变量 MEDIA_UPLOAD_TOKEN\n"
            "  2) 把 Token 写进 %USERPROFILE%\\.media_upload_token\n"
            "  3) 临时用 --token 传入", 2)

    if args.usage:
        report_usage(upload_url, token, timeout, args.warn_mb)
        return

    if not args.file:
        die("缺少 --file", 2)
    path = os.path.abspath(args.file)
    if not os.path.isfile(path):
        die("文件不存在：%s" % path, 2)
    with open(path, "rb") as fh:
        raw = fh.read()
    if not raw:
        die("文件是空的：%s" % path, 2)
    if len(raw) > MAX_BYTES:
        die("图片 %.1f MiB，超过 16 MiB 上限，先压缩或降尺寸：%s" % (len(raw) / 1048576.0, path), 2)
    content_type = sniff_content_type(raw)
    if not content_type:
        die("不是 PNG/JPEG/WEBP（按文件头判断）：%s" % path, 2)

    quality = args.jpeg_quality
    if quality is None and os.environ.get("MEDIA_UPLOAD_JPEG_QUALITY"):
        try:
            quality = int(os.environ["MEDIA_UPLOAD_JPEG_QUALITY"])
        except ValueError:
            die("MEDIA_UPLOAD_JPEG_QUALITY 不是整数", 2)
    if args.max_side and quality is None:
        quality = 92                     # 只想缩尺寸时默认质量
    if quality is not None:
        if not 1 <= quality <= 100:
            die("--jpeg-quality 必须在 1-100（当前 %s）" % quality, 2)
        raw, content_type = compress_to_jpeg(raw, quality, os.path.basename(path), args.max_side)
        if len(raw) > MAX_BYTES:
            die("压缩后仍超过 16 MiB：%s" % path, 2)

    digest = hashlib.sha256(raw).hexdigest()

    if args.dry_run:
        sys.stderr.write(
            "POST %s\n  X-Upload-Token: %s****\n  Content-Type: %s\n  字节数: %d\n  sha256: %s\n"
            % (upload_url, token[:4], content_type, len(raw), digest))
        return

    started = time.time()
    status, body = upload(upload_url, token, raw, content_type, timeout)
    try:
        payload = json.loads(body) if body else {}
    except ValueError:
        payload = {}

    if status != 200:
        code = ""
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                code = err.get("code") or ""
        hints = {
            401: "Token 不对或没传（X-Upload-Token）",
            413: "图片超过 16 MiB",
            415: "不是 PNG/JPEG/WEBP",
            429: "同一 IP 超过 60 次/分钟，稍后重试",
            500: "服务器写盘失败",
        }
        die("上传失败 HTTP %s %s\n%s\n%s" % (status, code, hints.get(status, ""), body[:500]), 3)

    url = payload.get("url")
    if not url or not str(url).startswith("http"):
        die("服务器没返回 url：%s" % body[:500], 3)
    remote_sha = payload.get("sha256")
    if remote_sha and remote_sha != digest:
        die("sha256 不一致，传输可能被截断\n本地 %s\n远端 %s" % (digest, remote_sha), 4)

    sys.stderr.write("已上传 %.0f KiB，用时 %.1fs\n" % (len(raw) / 1024.0, time.time() - started))
    print(url)


if __name__ == "__main__":
    main()
