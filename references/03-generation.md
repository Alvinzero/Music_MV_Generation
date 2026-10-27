# 第三步：提示词与批量生成（图 → 视频）

> **生成入口已换成第三方媒体网关**，一律用 `scripts/media_api.py` 调用，
> 不再使用内置 ImageGen / VideoGen。地址、Key、模型参数、首帧公网 URL、费用与错误处理
> 全部见 `references/15-media-api.md`（动手前必读）。本文只管提示词和验收。

这一步把"意象表"变成画面。分两段：先出**场景图**，再由场景图出**视频**。
每段都有固定的提示词结构，照结构写，别自由发挥。

---

## 一、先把分镜表定下来

```bash
python scripts/song_structure.py --audio song.m4a -o out/structure.json
```

规则（实测出来的，不是拍脑袋）：

| 段落 | 参考槽位 | 为什么 |
|---|---|---|
| 前奏 | 6–10s | 观众还在进来，慢一点留人 |
| 主歌 | 5–8s | 讲事情，镜头要留得住 |
| 预副歌 | 4–5s | 开始加速，为副歌铺垫 |
| **副歌** | **3–4s** | 切得密才有劲；重复段更要换景 |
| 桥 / 尾奏 | 8–12s | 落下来，给一个收束的画面 |

**接口给到 4–15 秒**（Kling 3–15 / MiniMax 4–15）——「单镜 6 秒」这条老规矩已经不成立，
那个 6.04s 是旧内置生成器的上限，不是现在网关的。**时长从「固定档位」改成「按内容算」**：

```
seconds = clamp(max(ceil(歌词演唱时长), 动作所需, 情绪所需), 4, 15)
```

| 判据 | 怎么量 | 落到秒数 |
|---|---|---|
| **歌词** | 该镜覆盖的那句，从 lyric 时间轴算演唱时长 L | `≥ ceil(L)`，**一句不许跨两镜唱** |
| **动作** | 动作分几段 | 微动 4；单一动作 4–6；复合动作（走两步再回头）6–10；段落级运动（长推轨）10–15 |
| **情绪** | 要不要「停一下」 | 空镜 / 收尾 / 桥段 8–12，**一次生成，别拼** |

槽位与生成的关系（这三条最容易搞错）：

- **槽位 <4s**（副歌快切 3.2s）→ 时间轴照常排 3.2s，**生成按 4s**，多出的 0.8s **裁尾**。
  方向不能反：裁头会让首帧对不上构图，而首帧就是你上传的那张图。
- **槽位 >15s** → **必须拆镜**，拆点选歌词换行处或动作间隙。别靠慢放（慢放只到 2.5x，会糊）。
- **槽位 4–15s** → 生成 `ceil(槽位)`，保证 clip 不短于槽位，否则吸附拍点后移时会露黑边。

**长镜的代价与验收**

| 秒数 | 4 | 6 | 8 | 10 | 12 | 15 |
|---|---:|---:|---:|---:|---:|---:|
| Kling 1080P 积分 | 91 | 137 | 183 | 229 | 274 | 343 |

价格随秒数线性，所以**一个 15s 和两个 7.5s 同价**——但长镜少一处拼接缝、少一次首帧上传，
通常更值。代价是漂移会累积：**>8s 必须抽首/中/末三帧**验收（亮度爬升、纸纤维形变、机位游走），
**>12s 只给静态空镜或极慢运动**。

分镜表先给用户确认，再动图。表长这样：

| # | 起止 | 时长 | 歌词 | 画面（一句话） | 意象 |
|---|---|---|---|---|---|
| s01 | 0.0–5.9 | 5.9 | — | 夜巷纸幡，歌名进场 | 片头 |
| s08 | 44.7–48.6 | 3.9 | 固执的自转陀螺 | 陀螺在纸台面上高速旋转，顶光 | 陀螺 |

### 面向抖音：分镜表先过双轨检查

面向抖音时，分镜表必须同时带推流字段和生成字段，字段定义见 `references/13-douyin-storyboard.md`：

- 推流：`traffic_role / audience_question / change_type / repeat_of / upgrade`
- 生成：`visual / camera / continuity / image_prompt / motion_prompt / negative / backup_prompt / acceptance`

```bash
python scripts/narrative_lint.py out/shots.json                 # 关3后检查
python scripts/narrative_lint.py out/shots.json --production    # 批量前检查
```

**不要把推流任务写进 prompt 让模型理解。** “提升留存”“钩子更强”是剪辑与叙事指令，
生图模型不需要知道；prompt 只写能被画出来的主体、动作、环境、光、材质和构图。

---

## 二、场景图提示词：七段式

**结构固定，顺序固定。** 缺一段，出图就会偏：

```
[1 主体] + [2 动作/状态] + [3 环境] + [4 光] + [5 材质] + [6 构图] + [7 风格后缀]
```

| 段 | 写什么 | 反例（写了等于没写） |
|---|---|---|
| 1 主体 | 具体物件/角色，带数量 | "something beautiful" |
| 2 动作 | 一个能定格的瞬间 | "moving"（模型不知道停在哪） |
| 3 环境 | 空间 + 背景层次 | 只写"background" |
| 4 光 | **方向 + 冷暖 + 强弱** | 只写"cinematic lighting" |
| 5 材质 | 纸/布/陶/湿面，最好带触感 | "detailed" |
| 6 构图 | 景别 + 机位 + 主体位置 | 不写就随机 |
| 7 风格后缀 | 从 `style.md` 原样抄 | 每镜现编 |

一条合格的长这样：

```
[1] a small paper spinning top, [2] spinning fast, slightly tilted, losing balance,
[3] on a dark paper tabletop, empty room behind, layered paper shadows,
[4] one narrow beam of warm amber light from directly above, everything else near black,
[5] torn paper edges, visible fibre, soft matte surface,
[6] extreme close-up, centred, low camera angle,
[7] handcrafted paper-cut diorama, tilt-shift macro photography, deep indigo night
negative: text, letters, watermark, logo, extra limbs, photorealism, 3d render
```

### 三条硬规矩

1. **一个镜头只写一个主体**。两个主体抢戏，模型每次都会选不同的那个。
2. **光必须写方向**。没有方向的提示词，出图一定平——这是最便宜的"高级感"来源。
3. **negative 每次都写**，至少 `text, letters, watermark, logo`。少一次就多一张废图。

### 每镜写 2–3 条候选

按 `references/02-scoring.md` 的 **L3 分镜卡**打分，选 1 主 1 备。
**这一步不能省**——同一句话，三种写法出来的差别，比换个风格还大。

---

## 三、批量出图

### 并发怎么发

用脚本自带的批量入口，**并发 4–8**（默认 4，不要开到 40）。原因：
- 上游会限流（429），并发越高越容易触发，而且限流时不许并发重试
- 分批出完就能分批检查，早发现风格跑偏

```bash
python scripts/media_api.py jobs --kind image --shots out/shots.json \
    --out-dir images --size 1920x1080 --out work/image_jobs.json
python scripts/media_api.py batch --jobs work/image_jobs.json --concurrency 4
```

**每条提示词用唯一前缀**：`s07a_`、`s07b_`（镜号 + 候选号）。产物落进 `generated-images/`，
再按镜号归到 `images/s07.png`。已完成项会自动跳过，失败项改完提示词重跑同一条命令即可。

### 出图参数

| 项目 | 值 | 说明 |
|---|---|---|
| 模型 | `hunyuan-image-alpha` | 局部修改用 `hunyuan-image-alpha-edit`（`edit` 子命令） |
| 尺寸 | `1920x1080`（16:9）/ `1024x1536`（3:4 封面） | 总像素 ≤ 420 万；**实测上游按 16 取整**：要 1920x1080 实得 **1920x1072**，所以下游一律按"实得尺寸"走，别假设 1080 |
| 张数 | 每镜 1 张（`n` 只能为 1） | 候选靠"多条提示词"，不是"一条出多张" |
| 取结果 | `data.data[0].url` | 签名 URL 会过期，脚本已自动立刻下载 |

### 出图后必做的三件事

1. **裁水印 + 归一化尺寸（一条命令）**。水印固定在图**右下角**「AI生成 WORKBUDDY」，
   实测在 1920 宽上占右侧约 **145px**、底部约 **90px**，且**关不掉**（文生图没有 watermark 参数）。
   ```bash
   python scripts/crop_watermark.py --src images/s07.png --out images/s07c.png \
          --right 145 --bottom 90 --size 1920x1080
   ```
   用固定边距（`--right/--bottom`）而不是自动检测：浅色地面会被误判成水印（实测误报 1.0）。
   换模型或换网关时先 `--json` 跑一次检测看 bbox，再写死边距。
   **这一步不能省**——视频会原样继承首帧的像素，图上有水印，视频里就有。
2. **人工筛**：主体完整吗？有没有多余肢体？有没有蹦出文字？构图和分镜表一致吗？
3. **不合格换备选**，不要"凑合着用"——一帧凑合，整段视频都跟着凑合。
   只是局部脏（水印、杂物、多一只手）可以走 `edit` 局部修，不必整张重出。

### 出完直接进图生视频（不问）

图片全部裁完、筛过、不合格的已换备选，就**直接开始批量出视频**。
不要问"图片好了，要开始生成分段视频吗"——关2/关3 已经授权过了，这一问只会打断连续执行。
同理，一批出完接着下一批，直到每一镜都有可用片段。

---

## 四、图生视频

**进入本节的条件**：场景图已就绪 + 关2 样张已确认 + 关3 分镜已定 + **首帧已是公网 URL
（或配好 `MV_MEDIA_UPLOAD_CMD` 上传钩子）**。图生视频只接受 http(s) URL，不接受本地路径或 data URL。
条件齐了就直接跑，不设"征询开始"这一步。全片每镜都走这条链，**不用静帧推拉凑镜**。

```bash
python scripts/media_api.py jobs --shots out/shots.json \
    --images-dir images --out-dir clips_raw --out work/video_jobs.json
python scripts/media_api.py batch --jobs work/video_jobs.json --concurrency 4
# 中断/超时：wait 续等或重跑 batch，**不要重新提交**
```

### 批量之后：逐镜抽首末帧，四件事一眼过

**静帧好看 ≠ 动起来好看。** 视频的崩法在图上一律看不出来，只能出完再验：

| 崩法 | 表现 |
|---|---|
| 主体变形 | 纸片融化、角色换脸 |
| 运镜跑偏 | 推过头把主体裁掉，或被拉远 |
| 纹理糊掉 | 纸纹变塑料、边缘发毛 |
| 亮度漂移 | 长镜里越跑越亮（>8s 尤其明显），接下一镜像跳档 |

```bash
# 每镜抽首末两帧拼一张，逐镜过
ffmpeg -y -ss 0   -i clips/s07.mp4 -frames:v 1 /tmp/a.png
ffmpeg -y -sseof -0.1 -i clips/s07.mp4 -frames:v 1 /tmp/b.png
```

发现问题**只重出那一镜**，不要整批重来。重出时先换备选提示词，再考虑改机位写法
（`locked-off` ↔ `slight parallax drift`），最后才退到 zoompan 推镜。

> 预算特别大的片子（80 镜以上），可以自己抽 1 条先试运动，省得批量后大面积返工。
> **这是可选动作，不是流程关卡**——默认直接批量，出完逐镜验。

### 提示词只写"动"，不写"是什么"

画面已经在首帧里了，再描述内容只会让模型重新理解一遍，然后改掉你的构图。

```
❌ a paper spinning top on a table, dramatic lighting, camera pushes in slowly...
✅ the top keeps spinning smoothly, fine paper dust drifts through the beam,
   the camera pushes in very slightly; keep the paper texture crisp and unchanged
```

### 机位写死，别让它自己发挥

| 写法 | 模型会干什么 | 什么时候用 |
|---|---|---|
| `slow push-in` | 常常推过头（6 秒推 1.5 倍，字被裁掉） | 慎用，且必须抽末帧核对 |
| `Locked-off tripod shot` | 不动，只有环境在动 | **默认** |
| `slight parallax drift` | 轻微横移 | 空镜、城市全景 |

**抽首帧和末帧都要看。** 只看第一帧会被骗——上一版就是第一帧完美、末帧标题出画。

### 参数

```
model        : kling-video-v3   （省钱档 minimax-video-h3，但只有 768P/2K 且音轨关不净）
seconds      : 4–15 按内容算     （Kling 3–15 / MiniMax 4–15；jobs 用 --min-seconds 4 --max-seconds 15 夹住）
resolution   : 1080P            （MiniMax 只能 768P 或 2K）
enable_audio : false            （歌曲独立混音，不要生成音）
watermark    : false            （网关默认 true，必须显式关）
aspect_ratio : 16:9             （仅文生视频；图生视频幅面由首帧决定）
image_url    : 首帧公网 URL      （可再加 last_image_url 作尾帧，给了尾帧必须给首帧）
```

视频是异步任务：提交 → 每 5 秒轮询 → 完成立刻下载。
**提交不自动重试**；502 `submission_uncertain` / `missing_task_id` 时先查任务与积分，
续等用 `wait`，重跑用 `batch`（已完成自动跳过）。

### 三个固定 negative

```
morphing, warping, melting, changing characters, extra text, watermark, logo
```

纸雕类再加：`rippling paper, crumpled surface`。

### 成本只是排期，不是取舍依据

单镜大约 8 分钟（出图 + 出视频 + 抽帧验收）。40 镜 ≈ 5 小时，含重试。

**重试不设上限。** 崩了的镜头就重出，不要因为"已经试过两次"就留着——
一个糊镜头会在成片里被看三十遍。

## 五、失败处理（一定要有预案）

| 症状 | 原因 | 处理 |
|---|---|---|
| 主角换了个人/换了形状 | 提示词里主体描述不够具体 | 换备选提示词；或在首帧图里把主体做小一点 |
| 构图跑了（推远/裁切） | 机位没锁住 | 换 `locked-off`；或改回 zoompan |
| 出现文字/logo | negative 漏了 | 重出；出图阶段就要拦住 |
| 动作糊成一团 | 运动描述太复杂 | 只留一个动作 |
| 整镜不好看 | 分镜本身有问题 | **换镜，不要修**——修一镜的时间够重做三镜 |

**每一镜都必须有备选。** 没有备选的时候，你会不自觉地"凑合"，而凑合是成片质量的真实上限。

### 抖音项目再加一项验收：首帧是否完成推流任务

除主体、运镜、纹理、亮度外，回到 `traffic_role` 逐镜核对：

- `hook`：首帧是否能看懂异常、目标或结果
- `world`：是否补上了世界规则，而非只换了一个好看场景
- `escalation/turn`：关系或后果是否真的发生变化
- `payoff/comment`：是否形成情绪落点或具体讨论点

首帧没完成任务的镜头，即使画面精美，也要换镜或重排，不得用“好看”抵消“无信息”。
