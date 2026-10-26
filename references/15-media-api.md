# 生成接口：第三方媒体网关（替代内置 ImageGen / VideoGen）

**这条链上不再出现内置 ImageGen / VideoGen。** 文生图、图生图、文生视频、图生视频
统一走 `scripts/media_api.py`，背后是网关 `http://152.136.41.242:8788` 的四个模型。

- 图片是**同步**接口：请求返回里直接给结果 URL。
- 视频是**异步**接口：提交拿 `task_id` → 轮询 → 下载，**提交响应不是视频**。
- 结果 URL 都是临时签名地址，**必须立刻下载**，网关不做下载代理、不替你存结果。

---

## 一、配置（三步，不用改网关）

手册明确说**通常不需要改网关配置**：账号、`config.json`、端口、Key 原样可用，
媒体 UA 已内置。我们要配的只是**客户端这边**的两项：地址和 Key。

| 方式 | 写法 | 适用 |
|---|---|---|
| 环境变量（推荐） | `MV_MEDIA_BASE_URL`、`MV_MEDIA_API_KEY` | 本机长期使用，不进任何文件 |
| 本地配置文件 | 项目根目录 `media_api.local.json` | 多项目各自一套 Key |
| 命令行临时指定 | `--base-url` / `--api-key` / `--config` | 一次性验证 |

`media_api.local.json` 长这样（模板见 `assets/media_api.example.json`）：

```json
{
  "base_url": "http://152.136.41.242:8788",
  "api_key": "<API_KEY>",
  "upload_cmd": ""
}
```

**Key 要填网关主密钥或已启用的附加 Key，不是账号 accessToken。**
`media_api.local.json` 和 `*.local.json` 已加进 `.gitignore`，真实 Key 不进仓库、不进日志。

```bash
# 自检：能列出模型目录就说明地址和 Key 都对了
python scripts/media_api.py models
# 401 invalid_api_key = Key 错；连接失败 = 地址/网络问题
```

可选的网关侧配置（一般用不到，改完要重启容器）：
`upstream.media_user_agent`（空值用默认媒体 UA，也可用 `WB2A_MEDIA_USER_AGENT` 覆盖）、
`cn.chat_base`（默认 `https://copilot.tencent.com`，别动）、
`models.hidden`（模型黑名单，对媒体调用同样生效，被隐藏的模型直接返回 `model_unavailable`，不会打到付费上游）。

---

## 二、四个模型与全部可选参数

### 1. 文生图 `hunyuan-image-alpha` → `POST /v1/images/generations`

| 字段 | 必填 | 可选值 / 说明 |
|---|---|---|
| `model` | 是 | 固定 `hunyuan-image-alpha` |
| `prompt` | 是 | 非空文本 |
| `size` | 否 | `宽x高`，默认 `1024x1024`；正整数，**总像素 ≤ 4,200,000** |
| `n` | 否 | **只允许 1**（防误产生批量费用）；要多张就多次调用 |
| `response_format` | 否 | 原样转发；混元通常返回 URL |

`size` 合法示例：`1024x1024`、`1024x1536`、`1536x1024`、`2048x2048`、`2560x1440`。
**本片默认：正片镜 `1920x1080`（16:9 原生，免裁比例），封面 `1024x1536`（3:4）。**

成功响应里取 `data.data[0].url`，`data.usage.credit` 是实际积分。

### 2. 图生图 / 改图 `hunyuan-image-alpha-edit` → `POST /v1/images/edits`

| 字段 | 必填 | 可选值 / 说明 |
|---|---|---|
| `model` | 是 | 固定 `hunyuan-image-alpha-edit` |
| `prompt` | 是 | 编辑要求，如"保持主体不变，把背景改成蓝色天空" |
| `image` | 是 | **data URL 字符串或数组**：`data:image/png;base64,...` / `data:image/jpeg;base64,...` |
| `size` | 否 | 同文生图 |
| `n` | 否 | 只允许 1 |
| `input_fidelity` | 否 | 原样转发上游 |

限制：单张解码后 **≤ 8 MiB**，整个请求体 **≤ 16 MiB**；
**不支持** `file://`、本地路径、远程 http(s) URL 当输入。
**注意这和视频正好相反**：改图只要 data URL，视频首帧只要公网 URL。

### 3. 视频 `minimax-video-h3` / `kling-video-v3` → `POST /v1/videos/generations`

| 能力 | `minimax-video-h3` | `kling-video-v3` |
|---|---|---|
| 文生视频 / 图生视频 | 都支持 | 都支持 |
| 秒数 | **4–15**（默认 5） | **3–15**（默认 5） |
| 分辨率 | **768P、2K**（默认 768P） | **720P、1080P、4K**（默认 720P） |
| 宽高比 | `adaptive`、`21:9`、`16:9`、`4:3`、`1:1`、`3:4`、`9:16`（默认 `adaptive`） | `16:9`、`9:16`、`1:1`（默认 `16:9`） |
| 音频 | `always-on`，`enable_audio:false` 也**可能仍带非静音音轨** | `switchable`，`enable_audio:false` 有效 |
| 提示词长度 | ≤ 2000 字符 | ≤ 2500 字符 |
| 首帧 / 首尾帧 | 支持 | 支持 |

通用字段：

| 字段 | 说明 |
|---|---|
| `model` / `prompt` | 必填 |
| `seconds` | 整数秒，缺省 5 |
| `negative_prompt` | 负向提示，默认空 |
| `watermark` | **默认 true**；本流程默认显式传 `false` |
| `resolution` / `enable_audio` / `aspect_ratio` | 便捷字段，会合并进 `extra_parameters` |
| `aspect_ratio` | **仅文生视频使用**；图生视频幅面由首帧决定 |
| `extra_parameters` | 上游原生参数对象；与便捷字段同现时**以它为准** |
| `image_url` | 首帧图 **http(s) URL** |
| `last_image_url` | 尾帧图 URL；**给了尾帧必须同时给首帧** |

实际时长按整数帧封装，可能和请求秒数略有出入；实测样本均为 **24 fps**，目录没有 fps 参数。

**本片默认：`kling-video-v3` + `1080P` + `enable_audio=false` + `watermark=false` + `16:9`。**
理由：1080P 是原生 1080p，不用把 768P 拉成 1080；Kling 能真正关音轨，MiniMax 关不掉。
省钱档是 `minimax-video-h3` + `768P`，但要接受清晰度与残留音轨（音轨反正会被原曲覆盖）。

> 新模型支持 15 秒，**不等于可以把单镜拉长到 15 秒**。分镜节奏仍按 `04a-timeline.md`，
> 长镜只在剧情真的需要时用，且要把时长写进 timeline。

### 4. 轮询 `POST /v1/videos/tasks`

```json
{"task_id": "1312831544-WandVideo-xxxxxxxx"}
```

`data.status`：`in_progress` → `completed` / `failed`。
完成后视频地址在 `data.data[0].url`，积分在 `data.usage.credit`。
**每 5 秒查一次，并设总等待上限**（脚本默认 1800 秒）。
`failed` 是上游任务状态，不是网关 HTTP 错误。

---

## 三、图生视频的首帧必须是公网 URL

这是换接口后**唯一的新增前置条件**：以前本地图直接喂给 VideoGen，现在不行。
三种解法，任选其一：

1. **先传图床 / OSS**，把 URL 直接给 `--first-frame`。
2. **配上传钩子**，脚本自动上传（推荐批量时用）：

   ```bash
   # {path} 会被替换成图片绝对路径；命令须在最后一行 stdout 打印 URL
   export MV_MEDIA_UPLOAD_CMD="python my_oss_upload.py {path}"
   ```

   也可以写进 `media_api.local.json` 的 `upload_cmd`，或单条命令用 `--upload-cmd`。
3. 批量清单 `jobs` 里直接给每条任务写 `first_frame` 为 URL。

没配钩子又给了本地路径，脚本会**直接报错并说明怎么配**，不会静默退化成文生视频。

---

## 四、命令速查

```bash
# 目录自检
python scripts/media_api.py models

# 文生图：正片镜 16:9 / 封面 3:4
python scripts/media_api.py image --prompt-file work/s07_image.txt \
    --size 1920x1080 --out images/s07.png
python scripts/media_api.py image --prompt-file work/cover.txt \
    --size 1024x1536 --out cover/cover.png

# 图生图（修图、去杂物、改背景）
python scripts/media_api.py edit --input images/s07.png \
    --prompt "保持构图不变，去掉右下角的水印" --size 1920x1080 --out images/s07_fix.png

# 图生视频（默认 Kling 1080P / 6s / 无音轨 / 无水印）
python scripts/media_api.py video --prompt-file work/s07_motion.txt \
    --first-frame images/s07.png --seconds 6 --out clips_raw/s07.mp4

# 文生视频（无首帧时才需要 aspect_ratio）
python scripts/media_api.py video --prompt "纸雕夜城，雨丝缓慢下落" \
    --model minimax-video-h3 --resolution 768P --seconds 4 --aspect-ratio 16:9 --out work/test.mp4

# 指定尾帧（必须同时给首帧）
python scripts/media_api.py video --prompt-file work/s07_motion.txt \
    --first-frame images/s07.png --last-frame images/s07_end.png --out clips_raw/s07.mp4

# 批量：先从分镜表生成清单，再并发跑；中断后重跑同一条命令即可续跑
python scripts/media_api.py jobs --shots out/shots.json \
    --images-dir images --out-dir clips_raw --out work/video_jobs.json
python scripts/media_api.py batch --jobs work/video_jobs.json --concurrency 4

# 进程被杀 / 等待超时：凭 task_id 续等，**不要重新提交**
python scripts/media_api.py wait --task-id <ID> --out clips_raw/s07.mp4

# 任何子命令加 --dry-run：只打印请求体，不发请求、不花钱
python scripts/media_api.py --dry-run video --prompt "测试" --seconds 6 --out work/t.mp4
```

产物旁会写 `<产物>.json` 侧车文件：`task_id`、模型、秒数、分辨率、prompt、`credit`、字节数。
**这是排错和成本核算的依据，别删。**

---

## 五、费用（历史实测，只用于估算，不是费率承诺）

| 样本 | 实际结算 |
|---|---:|
| 混元文生图 1 张 | 约 5.71 积分 |
| MiniMax 4 秒 / 768P | 57.14 积分 |
| MiniMax 15 秒 / 768P | 214.29 积分 |
| Kling 4 秒 / 720P | 68.57 积分 |
| Kling 15 秒 / 720P | 257.14 积分 |

按 4 秒样本线性外推 6 秒、60 镜：**MiniMax 768P ≈ 5,100 积分，Kling 720P ≈ 6,200 积分**，
1080P 更高，图片另算约 350 积分。**实际以任务完成响应里的 `credit` 为准**，
高分辨率、长视频、开音频都会加价。先用最低秒数最低分辨率验证链路，再提档位。

`batch` 结束会汇总全部 `credit`，写入 `<jobs>.report.json`。

---

## 六、错误处理（这几条是省钱的关键）

| 情况 | 码 | 怎么办 |
|---|---|---|
| Key 缺失或错误 | 401 `invalid_api_key` | 换网关 Key，别用 accessToken |
| prompt 为空 / JSON 非法 | 400 | 修请求体 |
| 模型与端点不匹配 | 400 `invalid_media_request` | 按第二节模型表调 |
| 秒数 / 分辨率不支持 | 400 / `14407` | MiniMax 4–15 + 768P/2K；Kling 3–15 + 720P/1080P/4K |
| 请求体超限 | 413 | 压缩图片或减少张数 |
| Content-Type 非 JSON | 415 | 改 `application/json`（脚本已固定） |
| 上游限流 | 429 | 保留错误，稍后处理，**不要并发重试** |
| 无可用 CN 账号 | 503 | 查账号健康度和积分 |
| **提交结果不确定** | 502 `submission_uncertain` | **不要直接重复提交**，先查上游任务和积分 |
| 成功响应缺任务 ID | 502 `missing_task_id` | 不要重复提交，保留 `X-Request-Id` 排查 |

网关**不会**在结果不确定时自动换号重提，就是为了避免同一请求被计费两次。
脚本同样遵守：**提交不自动重试，只有查询和下载允许重试**；
超时后给的是 `wait` 续等命令，而不是重新生成。

退出码：`2` 参数/校验问题，`3` 提交结果不确定，`4` 上游任务失败，`5` 等待超时。

---

## 七、安全

- 真实 Key、账号 accessToken、结果签名 URL **不写进代码、日志或公开文档**。
- `media_api.local.json` 已在 `.gitignore`；仓库里只放 `assets/media_api.example.json`。
- 只开放这四个模型，其他模型 ID 网关入口直接拒绝。
- 图片接口只接受 JSON，没有 multipart 上传兼容层。
