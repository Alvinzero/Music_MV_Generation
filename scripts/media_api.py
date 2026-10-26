#!/usr/bin/env python3
"""第三方媒体网关客户端：文生图 / 图生图 / 文(图)生视频。

替代内置 ImageGen / VideoGen 的全部生成调用。只依赖 Python 标准库。

配置（优先级从高到低）：
  1. 命令行 --base-url / --api-key / --config
  2. 环境变量 MV_MEDIA_BASE_URL / MV_MEDIA_API_KEY / MV_MEDIA_CONFIG
  3. 配置文件 ./media_api.local.json（默认，已被 .gitignore 排除）

子命令：
  models                      查询媒体模型目录
  image                       文生图（hunyuan-image-alpha）
  edit                        图生图 / 改图（hunyuan-image-alpha-edit）
  video                       提交视频任务并轮询、下载
  wait                        仅凭 task_id 续等并下载（断点续跑）
  jobs                        从 out/shots.json 生成批量任务清单
  batch                       按清单并发生成，自动跳过已完成项

所有子命令都支持 --dry-run：只打印请求体，不发请求、不花钱。
"""

import argparse
import base64
import concurrent.futures
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "http://152.136.41.242:8788"
IMAGE_MODEL = "hunyuan-image-alpha"
EDIT_MODEL = "hunyuan-image-alpha-edit"
VIDEO_MODELS = ("minimax-video-h3", "kling-video-v3")
MAX_IMAGE_PIXELS = 4200000
MAX_EDIT_IMAGE_BYTES = 8 * 1024 * 1024
MAX_EDIT_BODY_BYTES = 16 * 1024 * 1024

# 退出码：2 参数/校验失败，3 提交结果不确定（禁止盲目重提），4 上游任务失败，5 等待超时
EXIT_UNCERTAIN = 3
EXIT_TASK_FAILED = 4
EXIT_TIMEOUT = 5


class MediaError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- 配置与 HTTP


def load_config(args):
    cfg = {}
    path = args.config or os.environ.get("MV_MEDIA_CONFIG")
    if not path and os.path.isfile("media_api.local.json"):
        path = "media_api.local.json"
    if path:
        if not os.path.isfile(path):
            raise MediaError("配置文件不存在: " + path, 2)
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    base = args.base_url or os.environ.get("MV_MEDIA_BASE_URL") or cfg.get("base_url") or DEFAULT_BASE
    key = args.api_key or os.environ.get("MV_MEDIA_API_KEY") or cfg.get("api_key")
    # 本地子命令（jobs / dry-run）不需要 Key；真正发请求时才强制校验
    return {"base_url": base.rstrip("/"), "api_key": key or "", "raw": cfg}


def request(cfg, method, path, payload=None, timeout=180):
    """返回 (status, json)。业务 code 非 0 也原样返回，由调用方判断。"""
    if not cfg["api_key"]:
        raise MediaError(
            "缺少 API Key。设环境变量 MV_MEDIA_API_KEY，或在项目根目录写 "
            "media_api.local.json（{\"base_url\": ..., \"api_key\": ...}）。"
            "注意：要填网关主密钥或附加 Key，不是账号 accessToken。", 2)
    url = cfg["base_url"] + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + cfg["api_key"])
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {"raw": body[:2000]}
        return exc.code, parsed
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MediaError("网络错误 %s %s: %s" % (method, path, exc), 1)


def check_business(status, result, action):
    """HTTP 或业务失败时抛出带定位信息的异常。"""
    code = result.get("code")
    if status == 200 and code in (None, 0):
        return result
    detail = json.dumps(result, ensure_ascii=False)[:800]
    if status == 502 and ("submission_uncertain" in detail or "missing_task_id" in detail):
        raise MediaError(
            "%s 提交结果不确定（HTTP 502）。**不要直接重复提交**，先去面板核对是否已计费/已建任务。\n%s"
            % (action, detail), EXIT_UNCERTAIN)
    if status == 401:
        raise MediaError("%s 401 invalid_api_key：Key 无效，检查是否用了网关 Key 而非 accessToken。\n%s"
                         % (action, detail), 2)
    if status == 429:
        raise MediaError("%s 429 上游限流：保留现场，稍后重试，不要并发重提。\n%s" % (action, detail), 1)
    if status == 503:
        raise MediaError("%s 503 无可用 CN 账号：检查账号健康度与积分。\n%s" % (action, detail), 1)
    raise MediaError("%s 失败 HTTP=%s\n%s" % (action, status, detail), 1)


def download(url, out, tries=3):
    """结果 URL 是临时签名地址，必须尽快下载。网关不提供下载代理。"""
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    last = None
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=180) as resp:
                with open(out, "wb") as fh:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
            size = os.path.getsize(out)
            if size < 1024:
                raise MediaError("下载结果异常小（%d 字节）：%s" % (size, out), 1)
            return size
        except Exception as exc:  # 网络抖动可重试下载，不涉及重复计费
            last = exc
            if attempt < tries:
                time.sleep(3 * attempt)
    raise MediaError("下载失败 %s: %s" % (url, last), 1)


def sidecar(out, info):
    path = out + ".json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=2)
    return path


def read_prompt(args):
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as fh:
            text = fh.read().strip()
    else:
        text = (args.prompt or "").strip()
    if not text:
        raise MediaError("prompt 不能为空（--prompt 或 --prompt-file）", 2)
    return text


def parse_size(size):
    m = re.fullmatch(r"(\d+)x(\d+)", size or "")
    if not m:
        raise MediaError("size 必须是 宽x高，例如 1920x1080", 2)
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        raise MediaError("size 必须为正整数", 2)
    if w * h > MAX_IMAGE_PIXELS:
        raise MediaError("size 总像素 %d 超过网关上限 %d" % (w * h, MAX_IMAGE_PIXELS), 2)
    return size


def validate_video_params(model, seconds, resolution):
    if model not in VIDEO_MODELS:
        raise MediaError("视频模型只支持 %s" % (VIDEO_MODELS,), 2)
    if model == "minimax-video-h3":
        if not 4 <= seconds <= 15:
            raise MediaError("MiniMax 秒数必须 4–15（当前 %s）" % seconds, 2)
        if resolution not in ("768P", "2K"):
            raise MediaError("MiniMax 分辨率只支持 768P / 2K（当前 %s）" % resolution, 2)
    else:
        if not 3 <= seconds <= 15:
            raise MediaError("Kling 秒数必须 3–15（当前 %s）" % seconds, 2)
        if resolution not in ("720P", "1080P", "4K"):
            raise MediaError("Kling 分辨率只支持 720P / 1080P / 4K（当前 %s）" % resolution, 2)


# ---------------------------------------------------------------- 首帧图片 → URL


def to_data_url(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as fh:
        raw = fh.read()
    if not raw:
        raise MediaError("图片为空: " + path, 2)
    if len(raw) > MAX_EDIT_IMAGE_BYTES:
        raise MediaError("图片超过 8 MiB（%d 字节），请先压缩再改图: %s" % (len(raw), path), 2)
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode())


def frame_to_url(value, args, cfg):
    """视频首帧/尾帧必须是公网 http(s) URL。本地文件走用户配置的上传钩子。"""
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("data:"):
        raise MediaError("视频输入图片不支持 data URL，必须给公网 http(s) URL", 2)
    if not os.path.isfile(value):
        raise MediaError("首帧文件不存在: " + value, 2)
    template = args.upload_cmd or os.environ.get("MV_MEDIA_UPLOAD_CMD") or cfg["raw"].get("upload_cmd")
    if not template:
        raise MediaError(
            "首帧是本地文件，但网关只接受公网 URL。请二选一：\n"
            "  a) 先把图片传到你的图床/OSS，再用 --first-frame 传 URL；\n"
            "  b) 配置上传钩子：环境变量 MV_MEDIA_UPLOAD_CMD，"
            "值为一条命令，{path} 会被替换成图片路径，命令把图片传上去并在最后一行 stdout 打印 URL。\n"
            "  例：MV_MEDIA_UPLOAD_CMD=\"python my_oss_upload.py {path}\"", 2)
    cmd = template.replace("{path}", '"%s"' % os.path.abspath(value))
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
    url = (proc.stdout or "").strip().splitlines()
    url = url[-1].strip() if url else ""
    if proc.returncode != 0 or not url.startswith("http"):
        raise MediaError("上传钩子未返回 URL（exit=%s）\nstdout: %s\nstderr: %s"
                         % (proc.returncode, proc.stdout[-500:], proc.stderr[-500:]), 1)
    log("  首帧已上传: " + url)
    return url


# ---------------------------------------------------------------- 子命令


def cmd_models(cfg, args):
    if args.dry_run:
        log("GET /v1/media/models")
        return
    status, result = request(cfg, "GET", "/v1/media/models", timeout=60)
    check_business(status, result, "媒体目录")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_image(cfg, args):
    prompt = read_prompt(args)
    payload = {"model": IMAGE_MODEL, "prompt": prompt, "size": parse_size(args.size), "n": 1}
    if args.dry_run:
        log(json.dumps({"POST": "/v1/images/generations", "payload": payload}, ensure_ascii=False, indent=2))
        return
    status, result = request(cfg, "POST", "/v1/images/generations", payload)
    check_business(status, result, "文生图")
    items = ((result.get("data") or {}).get("data")) or []
    if not items or not items[0].get("url"):
        raise MediaError("响应里没有图片 URL：\n" + json.dumps(result, ensure_ascii=False)[:800], 1)
    size = download(items[0]["url"], args.out)
    info = {"kind": "image", "model": IMAGE_MODEL, "size": payload["size"], "prompt": prompt,
            "out": args.out, "bytes": size, "credit": (result["data"].get("usage") or {}).get("credit"),
            "requestId": result.get("requestId") or result.get("request_id")}
    sidecar(args.out, info)
    log("OK %s (%d bytes, credit=%s)" % (args.out, size, info["credit"]))
    return info


def cmd_edit(cfg, args):
    prompt = read_prompt(args)
    images = [to_data_url(p) for p in args.input]
    payload = {"model": EDIT_MODEL, "prompt": prompt, "image": images,
               "size": parse_size(args.size), "n": 1}
    if args.input_fidelity:
        payload["input_fidelity"] = args.input_fidelity
    body_size = len(json.dumps(payload))
    if body_size > MAX_EDIT_BODY_BYTES:
        raise MediaError("请求体 %.1f MiB 超过 16 MiB，请减少图片数量或压缩" % (body_size / 1048576.0), 2)
    if args.dry_run:
        shown = dict(payload, image=["<%d 张 data URL，共 %d 字节>" % (len(images), body_size)])
        log(json.dumps({"POST": "/v1/images/edits", "payload": shown}, ensure_ascii=False, indent=2))
        return
    status, result = request(cfg, "POST", "/v1/images/edits", payload, timeout=300)
    check_business(status, result, "图生图")
    items = ((result.get("data") or {}).get("data")) or []
    if not items or not items[0].get("url"):
        raise MediaError("响应里没有图片 URL：\n" + json.dumps(result, ensure_ascii=False)[:800], 1)
    size = download(items[0]["url"], args.out)
    info = {"kind": "edit", "model": EDIT_MODEL, "prompt": prompt, "inputs": args.input,
            "out": args.out, "bytes": size, "credit": (result["data"].get("usage") or {}).get("credit")}
    sidecar(args.out, info)
    log("OK %s (%d bytes, credit=%s)" % (args.out, size, info["credit"]))
    return info


def build_video_payload(cfg, args):
    prompt = read_prompt(args)
    seconds = args.seconds
    resolution = args.resolution
    model = args.model
    validate_video_params(model, seconds, resolution)
    payload = {
        "model": model,
        "prompt": prompt,
        "seconds": seconds,
        "resolution": resolution,
        "enable_audio": args.enable_audio,
        "watermark": args.watermark,
    }
    if args.negative_prompt:
        payload["negative_prompt"] = args.negative_prompt
    # aspect_ratio 仅文生视频使用；图生视频的幅面由首帧决定
    first = frame_to_url(args.first_frame, args, cfg) if args.first_frame else None
    last = frame_to_url(args.last_frame, args, cfg) if args.last_frame else None
    if last and not first:
        raise MediaError("提供尾帧时必须同时提供首帧", 2)
    if first:
        payload["image_url"] = first
    if last:
        payload["last_image_url"] = last
    if not first and args.aspect_ratio:
        payload["aspect_ratio"] = args.aspect_ratio
    if args.extra_parameters:
        extra = json.loads(args.extra_parameters)
        # extra_parameters 与便捷字段同时出现时，以 extra_parameters 内已有值为准
        payload.update({k: v for k, v in extra.items() if k in ("resolution", "enable_audio", "aspect_ratio")})
        payload["extra_parameters"] = extra
    return payload


def poll_task(cfg, task_id, timeout, interval, out=None, meta=None):
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            status, result = request(cfg, "POST", "/v1/videos/tasks", {"task_id": task_id}, timeout=60)
            check_business(status, result, "查询任务 " + task_id)
        except MediaError as exc:
            if exc.code in (EXIT_UNCERTAIN, 2):
                raise
            log("  查询异常（%s），5 秒后再试" % exc)
            time.sleep(interval)
            continue
        data = result.get("data") or {}
        state = str(data.get("status", "")).lower()
        log("  [%03d] %s" % (attempt, state or "unknown"))
        if state == "failed":
            raise MediaError("上游任务失败：\n" + json.dumps(result, ensure_ascii=False)[:800], EXIT_TASK_FAILED)
        if state == "completed":
            items = data.get("data") or data.get("videos") or []
            if not items or not items[0].get("url"):
                raise MediaError("任务完成但没有视频 URL：\n" + json.dumps(result, ensure_ascii=False)[:800], 1)
            credit = (data.get("usage") or {}).get("credit")
            if out:
                size = download(items[0]["url"], out)
                info = dict(meta or {})
                info.update({"kind": "video", "task_id": task_id, "out": out, "bytes": size, "credit": credit})
                sidecar(out, info)
                log("OK %s (%d bytes, credit=%s)" % (out, size, credit))
            return {"task_id": task_id, "credit": credit, "url": items[0]["url"], "out": out}
        time.sleep(interval)
    raise MediaError("等待超时（%ds），task_id=%s。用 wait 子命令续等，不要重新提交。" % (timeout, task_id),
                     EXIT_TIMEOUT)


def cmd_video(cfg, args):
    payload = build_video_payload(cfg, args)
    if args.dry_run:
        log(json.dumps({"POST": "/v1/videos/generations", "payload": payload}, ensure_ascii=False, indent=2))
        return
    status, result = request(cfg, "POST", "/v1/videos/generations", payload, timeout=300)
    check_business(status, result, "提交视频")
    task_id = (result.get("data") or {}).get("id")
    if not task_id:
        raise MediaError("成功响应缺少任务 ID，不要重复提交。保留 X-Request-Id 排查：\n"
                         + json.dumps(result, ensure_ascii=False)[:800], EXIT_UNCERTAIN)
    log("task_id = " + task_id)
    meta = {"model": payload["model"], "seconds": payload["seconds"], "resolution": payload["resolution"],
            "prompt": payload["prompt"], "image_url": payload.get("image_url"),
            "last_image_url": payload.get("last_image_url"), "watermark": payload.get("watermark"),
            "enable_audio": payload.get("enable_audio"), "payload": payload}
    # 先落账 task_id：进程被杀也能用 wait 续等，不会重复计费
    if args.out:
        sidecar(args.out, dict(meta, kind="video", task_id=task_id, status="submitted", out=args.out))
    return poll_task(cfg, task_id, args.timeout, args.interval, out=args.out, meta=meta)


def cmd_wait(cfg, args):
    poll_task(cfg, args.task_id, args.timeout, args.interval, out=args.out,
              meta={"resumed": True})


def cmd_jobs(cfg, args):
    with open(args.shots, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    shots = doc.get("shots", doc) if isinstance(doc, dict) else doc
    jobs = []
    for shot in shots:
        sid = shot.get("id") or shot.get("shot")
        if not sid:
            continue
        if args.kind == "image":
            prompt = shot.get("image_prompt") or shot.get("prompt") or shot.get("visual")
            if not prompt:
                log("  跳过 %s：没有 image_prompt" % sid)
                continue
            jobs.append({
                "id": sid,
                "kind": "image",
                "model": IMAGE_MODEL,
                "prompt": prompt,
                "size": args.size,
                "out": os.path.join(args.out_dir, sid + ".png"),
            })
            continue
        prompt = shot.get("motion_prompt") or shot.get("motion") or shot.get("prompt")
        if not prompt:
            log("  跳过 %s：没有 motion_prompt" % sid)
            continue
        seconds = args.seconds
        for key in ("seconds", "duration"):
            if isinstance(shot.get(key), (int, float)) and shot[key] > 0:
                seconds = int(round(shot[key]))
                break
        jobs.append({
            "id": sid,
            "kind": "video",
            "model": args.model,
            "prompt": prompt,
            "seconds": seconds,
            "resolution": args.resolution,
            "enable_audio": False,
            "watermark": args.watermark,
            "negative_prompt": args.negative_prompt,
            "first_frame": shot.get("image") or os.path.join(args.images_dir, sid + ".png"),
            "out": os.path.join(args.out_dir, sid + ".mp4"),
        })
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, ensure_ascii=False, indent=2)
    log("已写出 %d 条任务 -> %s" % (len(jobs), args.out))


def _run_job(cfg, args, job):
    out = job["out"]
    done_path = out + ".json"
    if os.path.isfile(out) and os.path.isfile(done_path):
        try:
            with open(done_path, "r", encoding="utf-8") as fh:
                prev = json.load(fh)
            if prev.get("bytes"):
                log("[skip] %s 已完成" % out)
                return {"out": out, "status": "skipped", "credit": prev.get("credit")}
        except ValueError:
            pass
    # 已有 submitted 记录但没下载完：续等，不重新提交
    if os.path.isfile(done_path) and not os.path.isfile(out):
        try:
            with open(done_path, "r", encoding="utf-8") as fh:
                prev = json.load(fh)
            if prev.get("task_id") and prev.get("status") == "submitted":
                log("[resume] %s 续等 %s" % (out, prev["task_id"]))
                poll_task(cfg, prev["task_id"], args.timeout, args.interval, out=out, meta=prev)
                return {"out": out, "status": "ok", "credit": prev.get("credit")}
        except ValueError:
            pass

    if job.get("kind") == "image":
        ns = argparse.Namespace(
            prompt=job.get("prompt"), prompt_file=None, size=job.get("size", "1920x1080"),
            out=out, dry_run=False,
        )
        info = cmd_image(cfg, ns)
        return {"out": out, "status": "ok", "credit": (info or {}).get("credit")}

    ns = argparse.Namespace(**vars(args))
    # 批量清单里可省略的字段，补上单条 video 子命令的默认值
    defaults = {
        "prompt": None, "prompt_file": None, "model": "kling-video-v3", "seconds": 6,
        "resolution": "1080P", "aspect_ratio": "16:9", "negative_prompt": "",
        "enable_audio": False, "watermark": False, "first_frame": None, "last_frame": None,
        "extra_parameters": None, "upload_cmd": args.upload_cmd, "dry_run": False,
    }
    for key, value in defaults.items():
        setattr(ns, key, value)
    for key, value in job.items():
        setattr(ns, key, value)
    res = cmd_video(cfg, ns)
    return {"out": out, "status": "ok", "credit": (res or {}).get("credit")}


def cmd_batch(cfg, args):
    with open(args.jobs, "r", encoding="utf-8") as fh:
        jobs = json.load(fh)
    log("共 %d 条任务，并发 %d" % (len(jobs), args.concurrency))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(_run_job, cfg, args, job): job for job in jobs}
        for future in concurrent.futures.as_completed(futures):
            job = futures[future]
            try:
                results.append(future.result())
            except MediaError as exc:
                log("[FAIL] %s -> %s" % (job.get("out"), exc))
                results.append({"out": job.get("out"), "status": "failed", "error": str(exc), "code": exc.code})
    credit = sum(r.get("credit") or 0 for r in results)
    failed = [r for r in results if r["status"] == "failed"]
    report = {"total": len(results), "failed": len(failed), "credit": credit, "results": results}
    report_path = args.report or (args.jobs + ".report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    log("完成 %d / 失败 %d，累计 credit=%s，报告 %s" % (len(results) - len(failed), len(failed), credit, report_path))
    if failed:
        raise MediaError("有 %d 条失败，详情见报告。修好后重跑同一命令即可，已完成项会跳过。" % len(failed), 1)


# ---------------------------------------------------------------- CLI


def build_parser():
    p = argparse.ArgumentParser(description="第三方媒体网关客户端（替代 ImageGen / VideoGen）")
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--dry-run", action="store_true", help="只打印请求体，不发请求")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("models", help="查询媒体模型目录")
    sp.set_defaults(func=cmd_models)

    for name, help_text in (("image", "文生图"), ("edit", "图生图/改图")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--prompt")
        sp.add_argument("--prompt-file")
        sp.add_argument("--size", default="1920x1080", help="宽x高，默认 1920x1080，总像素 ≤4200000")
        sp.add_argument("--out", required=True)
        if name == "edit":
            sp.add_argument("--input", action="append", required=True, help="输入图片路径，可重复")
            sp.add_argument("--input-fidelity", default=None)
        sp.set_defaults(func=cmd_image if name == "image" else cmd_edit)

    def add_video_args(sp):
        sp.add_argument("--prompt")
        sp.add_argument("--prompt-file")
        sp.add_argument("--model", default="kling-video-v3", choices=VIDEO_MODELS)
        sp.add_argument("--seconds", type=int, default=6)
        sp.add_argument("--resolution", default="1080P")
        sp.add_argument("--aspect-ratio", default="16:9", help="仅文生视频使用")
        sp.add_argument("--negative-prompt", default="")
        sp.add_argument("--enable-audio", action="store_true", default=False)
        sp.add_argument("--watermark", action="store_true", default=False, help="默认不加水印")
        sp.add_argument("--first-frame", default=None, help="首帧：公网 URL 或本地图片（本地需配上传钩子）")
        sp.add_argument("--last-frame", default=None, help="尾帧，需同时给首帧")
        sp.add_argument("--extra-parameters", default=None, help="上游原生参数 JSON 字符串")
        sp.add_argument("--upload-cmd", default=None, help="本地上传钩子，{path} 占位")
        sp.add_argument("--out", default=None)
        sp.add_argument("--timeout", type=int, default=1800)
        sp.add_argument("--interval", type=int, default=5)

    sp = sub.add_parser("video", help="提交视频并等待下载")
    add_video_args(sp)
    sp.set_defaults(func=cmd_video)

    sp = sub.add_parser("wait", help="凭 task_id 续等并下载")
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--out", default=None)
    sp.add_argument("--timeout", type=int, default=1800)
    sp.add_argument("--interval", type=int, default=5)
    sp.set_defaults(func=cmd_wait)

    sp = sub.add_parser("jobs", help="从 shots.json 生成批量任务清单")
    sp.add_argument("--shots", required=True)
    sp.add_argument("--kind", choices=["video", "image"], default="video", help="生成视频任务还是出图任务")
    sp.add_argument("--size", default="1920x1080", help="kind=image 时的出图尺寸")
    sp.add_argument("--images-dir", default="images")
    sp.add_argument("--out-dir", default="clips_raw")
    sp.add_argument("--out", required=True)
    sp.add_argument("--model", default="kling-video-v3", choices=VIDEO_MODELS)
    sp.add_argument("--seconds", type=int, default=6)
    sp.add_argument("--resolution", default="1080P")
    sp.add_argument("--negative-prompt", default="morphing, warping, melting, changing characters, extra text, watermark, logo")
    sp.add_argument("--watermark", action="store_true", default=False)
    sp.set_defaults(func=cmd_jobs)

    sp = sub.add_parser("batch", help="并发生成，断点续跑")
    sp.add_argument("--jobs", required=True)
    sp.add_argument("--concurrency", type=int, default=4)
    sp.add_argument("--report", default=None)
    sp.add_argument("--timeout", type=int, default=1800)
    sp.add_argument("--interval", type=int, default=5)
    sp.add_argument("--upload-cmd", default=None)
    sp.set_defaults(func=cmd_batch, dry_run=False)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args)
        args.func(cfg, args)
    except MediaError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return exc.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
