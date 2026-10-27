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

网关自带的 18080 图床已经够用，而且有 HTTP 上传口——**不需要 SSH、不需要 paramiko、不需要装任何包**，任何能发 HTTP 的机器都能传。

### 3.1 图床参数

| 项目 | 值 |
|---|---|
| 读图 | `http://152.136.41.242:18080/frames/<UUID>.png` |
| 上传 | `POST http://152.136.41.242:18080/upload` |
| 鉴权头 | `X-Upload-Token: <TOKEN>` |
| 请求体 | 图片**原始字节**（不是 multipart） |
| 格式 / 大小 | 仅 PNG / JPEG / WEBP（按文件头校验），单张 ≤ **16 MiB** |
| 频率 | 同一 IP **60 次/分钟**；超了返回 429 |

Upload Token 和网关的 API Key **不是同一个东西**，只在上传时用。配一次即可，三种写法：

- 环境变量 `MEDIA_UPLOAD_TOKEN`
- 写进文件：Windows `%USERPROFILE%\.media_upload_token`，Linux `~/.media_upload_token`
- 单次 `--token` 传入（不建议，会进命令历史）

### 3.2 手动传一张

```bash
python scripts/upload_frame.py --file work/s07.png
# stdout 只有一行 URL，可直接给 --first-frame
```

- `--check`：只查 Token 是否就位，不传
- `--dry-run`：只打印将要发送的请求（地址、Content-Type、字节数、sha256），不传
- 脚本会比对服务器回传的 `sha256`，不一致按传输截断报错，避免坏图混进任务

### 3.3 让批量脚本自动传（批量必配）

```bash
export MV_MEDIA_UPLOAD_CMD='python "C:/Users/<你>/.workbuddy/skills/Music_MV_Generation/scripts/upload_frame.py" --file {path}'
```

`{path}` 会被替换成图片绝对路径并自动加引号，路径含空格也安全。
也可以写进 `media_api.local.json` 的 `upload_cmd`，或单条命令用 `--upload-cmd`。

三条硬要求：命令**只在 stdout 打 URL**（日志走 stderr，否则 URL 会被日志污染）、**不要退化成文生视频**（会丢首帧构图控制）、上传失败就中断该条任务。

### 3.4 其它三种写法（一般不需要）

1. 已有 OSS / 别家图床 → URL 直接给 `--first-frame`。
2. 自己的上传脚本 → 只要最后一行 stdout 打印 URL，接进 `MV_MEDIA_UPLOAD_CMD`。
3. 批量清单 `jobs` 里直接给每条任务写 `first_frame` 为 URL。

没配钩子又给了本地路径，脚本会**直接报错并说明怎么配**，不会静默退化成文生视频。

### 3.5 图片不会被自动清理（重要）

图床**没有 TTL**，`/srv/media-frames` 会一直累积。60 镜一条片大约几十 MiB，短期不是瓶颈，但长期跑要管。

**查占用（客户端只读，不删）**：

```bash
python scripts/upload_frame.py --usage
# 超阈值时想直接拿到非零退出码，用于批量前拦截：
python scripts/upload_frame.py --usage --warn-mb 1024      # 或设 MEDIA_FRAMES_WARN_MB
```

底层是 `GET /upload/usage`（要 `X-Upload-Token`），返回 `files / bytes / stale_tmp / age_buckets / oldest_mtime / newest_mtime`，**只读快照**。

**真清理只能在服务器上跑**（本机没有 SSH，读不到那个目录）：

```bash
sudo python3 /home/ubuntu/tools/prune_frames.py --dir /srv/media-frames              # 默认只列不删
sudo python3 /home/ubuntu/tools/prune_frames.py --dir /srv/media-frames --older-than 7 --apply
```

护栏（工具内置，不靠人记）：默认不删；`--older-than` 必须 ≥1，0 会被拒绝；`--keep-last N` 保住最新 N 张；`.uploading-*` 半成品只清超过 1 小时的；不跟随符号链接、不递归。

**三条业务约束**：

1. **删了 URL 立即 404**，必须等视频任务完成后再清。MiniMax / Kling 通常几分钟出结果，保留 7 天余量很大。
2. 上游只在提交后短时间内读 `image_url`；**成片下载地址与图床无关**，清首帧不影响已生成视频。
3. 出片前查一次占用，超线先清再批量——不要等跑到一半才发现盘满。

---

### 3.6 右下角「AI生成 / WORKBUDDY」标（必读）

**图片：关不掉。** `hunyuan-image-alpha` 没有 `watermark` 参数，标是上游在处理阶段盖进像素的，
显式传 `watermark:false` 也一样有（实测：该区域峰值亮度 215，远高于周围纸面）。**出图后必须裁。**

**视频：参数能关，但有两个坑。**

1. 请求体里的 `watermark` **默认是 true**，必须显式 `false`（`media_api.py` 已经默认传 false）。
2. **首帧图带标，视频模型会把它当画面内容"拍"进去**，之后 `watermark:false` 只关叠加层，救不回画面里的标。
   所以顺序永远是：**先裁图 → 再上传当首帧 → 再出视频**。

**标的位置不稳定，别写死百分比。** 它是固定像素图章（约 110×52），画布越大占比越小；
视频流里又被放大过（1344 宽时约 167×75）。实测：

| 素材 | 尺寸 | 标的上边界 | 占高 | 需要的裁切 |
|---|---|---|---|---|
| 网关出图 | 1920×1072 | y=1009 | 94.1% | 底部 80px |
| MiniMax 768P 视频 | 1344×768 | y=692 | 90.1% | 底部 106px |

只裁 7% 在 1080p 上够用，在 **768P 上会留半截字**——这是我们踩过的坑。

**工具：`scripts/remove_label.py`**（Pillow；视频走 ffmpeg，自动 `-an` 去音轨）

```bash
python scripts/remove_label.py --input images/s07.png --output images/s07.png     # 就地覆盖
python scripts/remove_label.py --input clips_raw --output clips_new                # 整目录
python scripts/remove_label.py --input clip.mp4 --output clip.mp4 --dry-run --json # 只测不写
```

做法：固定像素 + 比例取大决定裁多少 → 只裁底部（不做左右对称裁，别丢构图）→
cover 缩放铺回原尺寸（`force_original_aspect_ratio=increase` + 居中裁，**不拉伸**）→
用「右下角热点密度」验收，没降下来就退出码 2。

实测验收：图 0.2111 → 0.0032；视频 0.1372 → 0.0047，放大 3 倍目视确认干净。

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

| 样本 | 实际结算 | 折合积分/秒 |
|---|---:|---:|
| 混元文生图 1 张 | 约 5.71 积分 | — |
| MiniMax 4 秒 / 768P | 57.14 积分 | 14.29 |
| MiniMax 15 秒 / 768P | 214.29 积分 | 14.29 |
| Kling 4 秒 / 720P | 68.57 积分 | 17.14 |
| Kling 15 秒 / 720P | 257.14 积分 | 17.14 |
| **Kling 4 秒 / 1080P** | **91.43 积分**（6 路并发实测，5 条一致） | **22.86** |

实测确认**按时长线性计费**，同档位不同并发、不同首帧，单价完全相同。1080P 比 720P 贵 33%，
比 MiniMax 768P 贵 60%。

按本片 60 镜、实际镜头时长取整（合计 286 秒）估算：

| 档位 | 全片估算 |
|---|---:|
| MiniMax 768P | 约 4,130 积分 |
| Kling 720P | 约 4,900 积分 |
| **Kling 1080P** | **约 6,540 积分** |

**实际以任务完成响应里的 `credit` 为准**，高分辨率、长视频、开音频都会加价。
先用最低秒数最低分辨率验证链路，再提档位。

> 注意：上游任务 `failed` 时不返回 `usage.credit`，脚本汇总里也不会计入。
> 但**无法确认上游是否已扣费**，失败重跑时按「已花掉」做预算更保险。

`batch` 结束会汇总全部 `credit`，写入 `<jobs>.report.json`。

---

## 5.1 两档画质差异（实测，决定要不要裁）

| | Kling 1080P | MiniMax 768P |
|---|---|---|
| 实际输出 | **1920×1080，24fps，97 帧/4s** | 1344×768（比例 1.75，非 16:9） |
| 音轨 | **0 条**（`enable_audio:false` 真的生效） | 1 条 AAC 32k（always-on，关不掉） |
| 水印 | **无**（`watermark:false` 生效） | 需实测；首帧带标会被拍进画面 |
| 进时间轴前 | **直接可用，不用 scale** | 必须 `scale` + 裁底部，损失约 10% 画面 |
| 单价 | 22.86 积分/秒 | 14.29 积分/秒 |

**结论：Kling 1080P 是唯一「出片即可用」的档位。** 省下的不是后期时间，而是画质——
MiniMax 768P 要裁掉底部 14% 再拉回 1080p，等于拿真实分辨率换钱。预算允许就上 Kling。

---

## 5.2 并发实测（6 路 Kling 1080P，2026-10-27）

一次提交 6 条、并发窗口 6，全程 4 分 19 秒：

| 指标 | 实测 |
|---|---|
| 6 条提交耗时 | **1.1 秒**（全部同一秒发完，无 429、无限流） |
| 首帧上传 6 张 | 3.4 秒（并发） |
| 单条完成耗时 | 177.7 / 192.3 / 202.9 / 244.9 / 248.4 秒 |
| 首条完成 | 176.7 秒 |
| 全部完成 | **247.4 秒** |
| 成功 / 失败 | 5 / 1 |
| 花费 | 457.15 积分（5 × 91.43） |

**上游不暴露排队。** 任务状态只有 `in_progress` / `completed` / `failed` 三种，
第一轮查询（提交后 1.8 秒）就已是 `in_progress`，**从来没有 `queued`**。
所以"有没有排队"没法从状态判断，只能看耗时：

- 6 条并发 247 秒 = 平均 41 秒/条的有效吞吐
- 若上游串行处理，第 6 条要排到 1200 秒以上；实际全部在 250 秒内完成
- 但**不是完全并行**：首条 177 秒、末条 248 秒，跨度 71 秒，说明存在资源竞争
- 与 MiniMax 单条 4s（168 秒）对比，Kling 1080P 慢不了多少 → **并发窗口 6 是安全的**

**唯一一次失败的根因不是并发限制：**

```
{"status":"failed","error":{"message":"Something went wrong when we tried to get the contents of the file."}}
```

这是**上游抓取首帧图失败**。复核那条 URL：现在能 200 打开、字节数正确，
但单次拉取要 **7.9 / 8.6 / 12.7 秒**（2.8 MB PNG）。也就是说 **图床下行太慢**，
上游等不到图就判失败。同批其他 5 张之所以成功，是运气比它好。

→ **对策：首帧先压 JPEG 再上传。** 1920×1080 的 PNG 2.75 MB，JPEG q92 只有 0.51 MB（19%），
拉取时间明显下降。`media_api.py batch` 重跑同一命令会自动跳过已完成项、只补失败项，
所以偶发失败不用整批重来——但要按「已计费」算预算。

## 5.3 图床带宽是硬约束（服务器侧实测）

登服务器查过，问题不在图床代码，在**公网出口带宽**：

| 测试 | 结果 |
|---|---|
| 服务器本地读图（127.0.0.1） | 3.6 MB **0.002 秒**（≈1.8 GB/s，纯内存/磁盘） |
| 经公网 IP 读同一文件 | 0.39 MB 要 **3.1 / 5.7 / 11.4 秒**（36–133 KB/s），偶发 40 秒不返回 |
| 网卡限速（tc） | **无**，qdisc 为默认 fq_codel |
| 同机其他业务 | 还跑着 LLM 代理，日志里有 429 限流 → **带宽与其他业务共享** |

所以**上游拉首帧慢/超时，是带宽被抢 + 链路抖动，不是文件大本身**。
压缩只能缓解，不能消除：0.39 MB 在 36 KB/s 下也要 11 秒，2.19 MB PNG 同样的链路直接爆表。

首帧体积与最坏情况下的拉取时间（按实测最低 36 KB/s 估）：

| 首帧 | 体积 | 最坏拉取 | 说明 |
|---|---:|---:|---|
| 1920×1080 PNG | 2.2–2.9 MB | 60 s+ | ✅ **默认用原图**，失败交给重投 |
| 1920×1080 JPEG q92 | ~400 KB | 11 s | PSNR 42.45 dB 肉眼无差；失败率飙升时再开 |
| 1440×810 JPEG q92 | ~250 KB | 7 s | PSNR 38.39 dB，边缘发软，非必要不用 |

**默认规格：不压缩，传原始 PNG。** 首帧虽然是条件输入而非成片，但能保真就别降级；
偶发拉取失败由批量重投兜住（见 5.4），比长期牺牲画质划算。

真要压缩时的取舍：同为 q92，1920 比 1440 高 **4.06 dB**（多 236 KB）；
同为 1440，q92 比 q88 只高 **1.02 dB**（省 79 KB）。
**损失画质的是降尺寸，不是 JPEG 那一步** —— 所以先降质量、别动尺寸。

`upload_frame.py` 保留压缩开关（`--jpeg-quality` / `--max-side` / 环境变量
`MEDIA_UPLOAD_JPEG_QUALITY`，上传超时默认 120 s），只在失败率明显上升时作为应急手段。

> 若以后图床迁到有独立带宽的机器，或改用对象存储 + CDN，这一节可以整体作废。

## 5.4 批量：并发池 + 失败立刻回队

`batch` 不是「一批跑完再统一重试」，而是**饱和式并发池**：`--concurrency N` 个线程常驻，
任何一条失败就立刻重新入队，由最先空闲的线程接手 —— **池子里始终有 N 条在跑**。

```bash
python scripts/media_api.py batch --jobs work/video_jobs.json \
    --concurrency 6 --retry 3 --retry-delay 0
```

| 参数 | 默认 | 说明 |
|---|---:|---|
| `--concurrency` | 6 | 常驻线程数（实测上游不排队，6 路安全） |
| `--retry` | 3 | 单条最多重投次数；0 = 不重投 |
| `--retry-delay` | 0 | 重投前等待秒数；0 = 立刻回队补位 |

三个细节都是踩过的坑：

1. **重投前必须先挪 sidecar**（脚本自动做，改名 `<out>.json.failed-rN`）。
   失败任务的 sidecar 里还留着 `status=submitted` 的旧 `task_id`，
   不挪走的话重投会去轮询那个死任务，一次重投机会直接白扔。
2. **等待超时（默认 30 分钟）不重投**，只标 `timeout` 并保留 sidecar。
   上游可能还在跑，重投等于重复计费；用 `media_api.py wait --task-id ...` 续等。
3. **重投会再花一次钱**。`--retry 3` 意味着最坏单条付 4 次，
   预算要按「总额 × 1.2」留量，不能按成功数算。

实测（8 条 / 并发 3 / c 前两次失败）：并发峰值稳定 3；c 在 0.26 s 失败、
0.72 s 就被重新捡起，没有「等全批」的空窗；一直失败的 e 调用次数精确停在 1+2=3。




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

---

## 八、实测校准（2026-10-26 首轮真实链路）

一次完整走通：1 张图（1920x1080 请求）+ 图床上传 + 1 条 4 秒/720P 视频。
**这一节是实测值，和上面的手册参数冲突时以这里为准。**

| 项目 | 实测结果 |
|---|---|
| 出图尺寸 | 请求 `1920x1080` → 实得 **1920x1072**（高度按 16 取整，1080 不是 16 的倍数） |
| 出图水印 | **必带**，右下角「AI生成 WORKBUDDY」，约占右侧 145px × 底部 90px（1920 宽基准），**无参数可关** |
| 图床上传 | 3.5 MiB / **1.7 秒**，返回 `http://<host>:18080/frames/<hash>.png` |
| 视频分辨率 | 请求 `720P` → 实得 **1284x716**；**跟随首帧比例**，不是固定 1280x720 |
| 视频时长 | 请求 4 秒 → **4.0417 秒 / 97 帧 / 24fps**（多 1 帧） |
| 音轨 | `enable_audio=false` → ffprobe 只有 1 条视频流，**确实没有音轨** |
| `watermark=false` | 生效，但**会原样继承首帧里的水印**——所以图必须先裁 |
| 耗时 | 4 秒视频约 **21 次轮询 ≈ 105 秒**；整条链路（图+传+视频）约 2 分钟 |
| 计费 | 图 5.71 + Kling 4s/720P 68.57 = **74.28 积分** |

**两类必须处理的偏差**

1. **尺寸不会等于请求值**。上游按 16 取整、视频跟随首帧比例。所有下游环节（时间轴、拼接、
   字幕定位）都要读实际尺寸，不能写死 1080。统一在裁水印那步用
   `crop_watermark.py --size 1920x1080` 一次拉正，后面全按 1920x1080 处理。
2. **水印只能靠裁**。没有开关，`watermark=false` 只管模型自己那层。裁的位置写死成边距
   （`--right 145 --bottom 90`），别依赖自动检测：浅色地面/纸面会被误判成水印（实测误报满分 1.0）。

**首轮遇到的错误与结论**

`502 submission_uncertain`：`dial tcp: lookup copilot.tencent.com: i/o timeout`（网关侧 DNS 抖动）。
请求根本没到上游，**没有建任务、没有计费**，立即重试一次即成功。
判断依据：错误信息是 `dial tcp` / `lookup` 这类连接期失败，不是 `timeout` 等待期失败或
`missing_task_id`。后者（已建任务但没拿到 ID）**必须先去面板核对，不能重试**。
