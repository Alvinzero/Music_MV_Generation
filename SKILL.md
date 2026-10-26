---
name: Music_MV_Generation
description: 从一首歌（或已有素材）做出一条可发布的音乐 MV——分析素材、推荐视觉风格、按打分机制产出脚本与分镜提示词、批量出图与图生视频、拼时间轴、定字幕样式、做片头与封面，最后输出过质检的 MP4。适用于"做一支 MV""歌曲配画面""歌词视频""AI 音乐视频""纸雕/动画风 MV""把这首歌做成视频"，以及"给已有片段配字幕出片""重做片头/字幕/封面"。当用户给出歌曲 mp3 + 歌词，或说"帮我做一支 MV""这首歌做成视频""字幕风格不对""做张发布封面"时使用。面向抖音时，额外执行首帧钩子、全曲留存、重复段升级、评论互动、系列识别与发布复盘流程。
agent_created: true
---

# Music MV Generation · 从一首歌到一条能发的片

**这个 skill 管整条链**：素材 → 风格 → 脚本 → 分镜 → 出图 → 出视频 → 拼片 → 字幕 → 片头 → 封面 → 质检交付。

它由原来两个 skill 合并而来（一个偏"从零造素材"，一个偏"后期成片"），
现在只有一条路：**先想清楚，再造素材，最后后期**。

核心信条四句话：

1. **AI 负责决策，工具负责精确**——任何时间值、规格、响度都必须实测，不许估算。
2. **先做多，再做少**——每个关键选择都要有候选、有打分、有淘汰，不是第一个想法就用。
3. **先推流叙事，再生成执行**——面向抖音时，每镜先有留存任务，再有画面与提示词；缺任务的镜头不进入批量。
4. **确认一次，跑到关4**——风格与样张点头后，全片默认 AI 生成；图出完直接出视频。
   **同一个问题不许问第二遍**，有默认值的执行细节一律按默认推进，事后再说明。

---

## 一、开工前必须问清的四件事

| 问题 | 为什么现在问 |
|---|---|
| 发哪儿？（抖音/快手/视频号/B站/YouTube） | 决定时长剪辑、字幕尺寸（封面一律 3:4，见 `07b-cover-brief.md`） |
| 主目标是什么？（冷启动播放/涨粉/收藏/系列回访） | 决定首帧、章节留存、评论问题和复盘口径；只选一个主目标 |
| 有没有参考 MV / 参考图？ | 有就先读它的调色、材质、镜头节奏、字幕样式（`01-brief.md` 第二节） |
| 歌词是最终版吗？ | 歌词一改，分镜和时间轴全废。**先锁歌词** |

**这四件事一次问完，别分四轮追问**；问完就开工，后面只有四道关该停。

顺手报个工期：40 镜大约 2–4 小时（出图 20 分钟 + 出视频 60–90 分钟，含重试）。

> **不为省积分牺牲质量。** 不合格就重做——重生成的代价只是时间，凑合的代价是整片废掉。

---

## 二、主流程（四道关 + 发布后回流）

```
⓪平台目标与对标 → ①素材分析 → ②风格选项 ═关1═ → ③样张迭代 ═关2═
→ ④推流剧情方案 → ⑤双轨分镜表 ═关3═ → ⑥分镜提示词 → ⑦批量出图
→ ⑧批量出视频 → ⑨片头 → ⑩时间轴/拼接 → ⑪字幕 → ⑫质检 ═关4═
→ ⑬封面 + 发布文案交付 → ⑭数据复盘回流
```

**关2 是一次性授权点：用户点头即同时确认了「风格锁死」和「全片默认 AI 生成」**，
之后不再就生成方式征询。**关3 通过后一路跑到关4**，中间（出提示词→出图→出视频→片头→拼接→字幕）
**没有任何提问点**。

**四道关都是跟用户交互**，不是自己判断完就往下走：

| 关 | 用户看到什么 | 用户要做什么 | 过关条件 |
|---|---|---|---|
| **关1 风格** | 5 个风格选项 + 推荐度 + 理由 | 选一个，或说"按推荐" | 明确选定**一个**主题 |
| **关2 样张** | 选定风格的 3 张静帧 | 通过，或指出改哪 | **说"可以"即同时授权全片 AI 生成** |
| **关3 分镜表** | 镜头 ↔ 歌词对照表 | 改镜、改顺序、砍镜头 | 确认后**一路跑到关4，不再问** |
| **关4 终版** | 粗剪 / 成片 | 提修改意见 | 确认后才出封面交付 |

**关卡纪律（六条）**

1. **不许自己替用户拍板**。到了关就停下来，把选项和推荐摆出来，等回复。
2. **每个选项都要说清代价**：多久、风险在哪、失败率多高。用户才能做判断。
3. **返修有上限**：样张最多 3 轮，每轮记下改了什么（更暖 / 更空 / 换材质）。
   第 3 轮还不对就回关1 重选风格，不要在错的风格上继续磨。
4. **样张没点头，不许批量**：图和视频都不许先出。样张是唯一能在低成本阶段看清方向的机会，
   跳过去就只能等整片出来才发现不对。
5. **不合格一律重做**：样张、片头、封面、单镜视频，只要验收不过就重新生成，
   **不许因为"已经花了不少"而将就**。重做的代价是时间，凑合的代价是整片废掉。
6. **关2 之后不再问生成方式，关3 之后不再问进度**：全片怎么生成、图出完要不要继续、
   下一批要不要开——这些都已由前两道关授权，重复询问只会打断连续执行。

### 默认决策表（这些一律不要问，直接按默认做）

| 容易被误问的 | 默认做法 |
|---|---|
| 全片都走 AI 生成吗？ | **是**。关2 通过即生效：镜镜「场景图 → 图生视频」 |
| 图片出完了，要开始出分段视频吗？ | **直接开**。抽检合格就接着批量，不停下来问 |
| 一批出完，继续下一批吗？ | **继续**，直到每一镜都有可用片段 |
| 某镜崩了，要不要重试？ | **换备选提示词重出单镜**，不整批重来，不问 |
| 要不要用静帧推拉 / 外部素材补几镜？ | **不用**。全片同一材质语言；只有个别镜连崩才退 zoompan 兜底 |
| 片头、时间轴、字幕之间还要确认吗？ | **不用**。一路做到关4 再给用户看 |
| 时长/帧率/画幅按什么来？ | 16:9、24fps、单镜 6s、1080P、`audio=false`，音频用完整原曲 |

> 只有两种情况值得停下来：**方向性选择**（风格、样张、叙事讲法、终版）和
> **不可逆的高成本动作**（比如整批重出）。其余全部按默认推进，做完在交付说明里写清做了什么。

### ⓪ 平台目标与对标 → `references/12-douyin-narrative.md`

面向抖音时先写 `out/douyin_brief.md`：目标观众、主目标、完整版/独立预告、系列任务。
再提取 3–5 个同形态样本的首帧、变化点、评论话题与可迁移结构；没有真实样本就标注“未做对标”，不编造热度。
这一步不做图，也不把热点元素硬贴到歌曲上，只确定本片要解决的留存问题。

### ① 素材分析 → `references/01-brief.md`

实测三件套，产出一张**意象表**（每句歌词 → 物件 / 空间 / 动作 / 光）：

```bash
python scripts/mediainfo.py assets/ -o out/manifest.json
python scripts/song_structure.py --audio song.m4a -o out/structure.json
python scripts/beat_sync.py song.m4a -o out/beats.json
```

**意象表是后面所有提示词的原料。** 某一格填不出来，那句歌词最后就会变成"配了张风景"。

### ② 风格选项 ══[关1]══ → `references/01-brief.md` 第四节

```bash
python scripts/style_advisor.py --audio song.m4a --lyrics lyrics.txt
```

出 **5 个**跨家族候选，按 L1 卡打分（情绪 0.30 / 素材 0.20 / 出图稳定 0.20 / 差异化 0.15 / 节奏 0.15），
**换算成推荐度 ★1–5**，做成一张选项卡给用户，**把推荐度最高的那个明确标出来**：

| | 风格 | 气质一句话 | 推荐度 | 代价 |
|---|---|---|---|---|
| ★推荐 | 纸雕夜城 | 暗纸 + 背光，孤独但有温度 | ★★★★★ 4.6 | 重试率低，出图最稳 |
| B | 厚涂插画 | 手绘笔触，情绪浓 | ★★★★ 4.1 | 出图重试率高 20% |
| … | | | | |

**这一关不烧图**，靠文字 + 关键词 + 参考帧就能选。用户说"按推荐"才直接采纳。

### ③ 样张迭代 ══[关2]══ → `references/01-brief.md` 第五节

**风格定下来之后**，用**这一个风格**出 **3 张**，覆盖三种镜头类型
（主体特写 / 空镜 / 情绪镜），而不是三个风格各一张——那验证不了风格本身撑不撑得住全片。

- 用户说"可以" → 进第 ④ 步，**这一声"可以"同时授权全片走 AI 生成**，写进 `style.md` 的确认记录
- 用户说"不行" → 记下**具体改哪**（更暖/更冷、更密/更空、换材质、字更重），只改这一项重出
- **最多 3 轮**；3 轮还不对，说明风格选错了，回关1

**过关前不许批量。** 3 张 vs 40 张，成本差 10 倍。
**过关后不许再问**：不再确认"全片是否都用 AI 生成"，那就是默认方案。

### ④ 推流剧情方案（L2 / L2-D 打分）

写 3 套分镜脚本（不是 3 个版本，是 3 种**讲法**）。通用项目按 L2 卡打分；面向抖音时按 L2-D 卡打分
（首帧钩子 0.25 / 留存曲线 0.20 / 歌词咬合 0.15 / 可生成 0.15 / 情绪曲线 0.10 / 互动 0.05 / 系列 0.05 / 可剪辑 0.05）。

```bash
python scripts/score_candidates.py out/score.json --layer script   # 通用剧情
python scripts/score_candidates.py out/score.json --layer douyin   # 抖音推流剧情
```

**评的是交付文件的第 0–3 秒，不是分镜表的第一镜**——片头第 ⑨ 步才做、做完置顶，
所以这里必须写清「开场画面 + 开场概念字」，并在交付前回到成片抽 0s/1s/3s 复核。
空镜开场、纯静态字牌开场都不合格。详见 `references/02-scoring.md`、`06-title-card.md` 第〇节。

抖音方案还必须写清：开唱前的世界规则、每 15–25 秒有效变化、重复副歌升级、唯一评论问题和系列识别。
命中 L2-D 否决项时，即使总分高也不能进入分镜表。

### ⑤ 双轨分镜表 ══[关3]══

面向抖音时使用 `references/13-douyin-storyboard.md` 的双轨分镜卡，不只写画面：

| # | 起止 | 歌词 | 推流任务 | 观众疑问 | 画面（一句话） | 衔接/备选 |
|---|---|---|---|---|---|---|

时长规则：前奏 6–8s、主歌 5–6s、副歌 **3–3.5s**、桥/尾 6–8s，**单镜 ≤6 秒**（硬上限 6.04s）。

**前奏超过 8 秒必须填信息**（`references/04a-timeline.md` 第 6 节）：
概念字 / 成品预告 / 制作过程快剪，三选二（前奏 >20 秒时）。
**最强镜不许留到开唱**，前奏里必须出现全片最强的 1–2 个图形镜。
**每 5 秒必须有一次新信息**（新画面 / 新字 / 新动作），逐段写得出来才算过。

抖音再加五条：
1. 首帧必须是异常、人物目标或结果预告，不能只是纸纹、折痕或制作信息。
2. 开唱前必须建立世界规则与危机；纯音乐前奏不能只做工艺展示。
3. 每镜必须有 `traffic_role` 和 `change_type`，重复段必须有 `repeat_of + upgrade`。
4. 每 15–25 秒必须有新信息、新关系、新后果或新目标，仅换滤镜/机位不算。
5. 分镜确认后先跑 `python scripts/narrative_lint.py out/shots.json`，通过再写生产提示词。

**关3 是最后一个内容确认点。** 用户点头之后就是**连续生产**：写提示词 → 出图 → 出视频 → 片头 →
拼接 → 字幕，一步接一步跑到关4。这中间不要回头问"要不要继续"，也不要把同一个方案再确认一遍。

> 硬约束：**画幅固定 16:9；音频是完整原曲，不二次剪辑、不缩短、不拆条。**
> 所以前奏长只能靠"这段放什么"解决，不能靠砍。

### ⑥ 分镜提示词（L3 打分）→ `references/03-generation.md`

每镜写 **2–3 条**场景图提示词，按"七段式"（主体/动作/环境/光/材质/构图/风格后缀）+ negative。
按 L3 卡打分，选 1 主 1 备，存进 `out/score.json`。
图生视频提示词只写运动；抖音分镜另需保留 `continuity / backup_prompt / acceptance`，
保证相邻镜头空间一致、失败能换备选、首末帧有明确验收标准。

```bash
python scripts/score_candidates.py out/score.json --layer shot
python scripts/narrative_lint.py out/shots.json --production
```

**可生成性红线**（命中直接扣）：手部特写 −1.5、画面内文字 −2.0、三人以上 −1.0、
精细机械 −1.0、清晰倒影 −0.5、复杂透视 −0.5、品牌/IP −2.0。

### ⑦ 批量出图（`media_api.py` · 混元文生图）

**不再调用内置 ImageGen**，全部走第三方网关。配置、模型参数、费用见 `references/15-media-api.md`。

```bash
# 1) 从分镜表生成出图清单（image_prompt → images/sNN.png）
python scripts/media_api.py jobs --kind image --shots out/shots.json \
    --out-dir images --size 1920x1080 --out work/image_jobs.json
# 2) 并发出图，断点续跑；有失败就修完重跑同一条命令，已完成项自动跳过
python scripts/media_api.py batch --jobs work/image_jobs.json --concurrency 4
```

- 正片镜 `1920x1080`（16:9 原生），封面 `1024x1536`（3:4）；总像素 ≤ 420 万。
- `n` 只能为 1，"多候选"靠多条提示词多次调用；候选命名沿用唯一前缀 `s07a_`。
- 出完**先检测水印再决定裁不裁**（不要盲套固定 crop 值），再人工筛，不合格换备选。
- 只是局部脏（水印、杂物、多一只手）可以用 `edit` 子命令局部修，不必整张重出。

**图出完不停顿**：全部裁完、抽检合格 → **直接进 ⑧**，不要问"要不要开始生成分段视频"。
批量中途也不问"继续下一批吗"——批次是执行细节，不是决策点。

### ⑧ 批量出视频（`media_api.py` · Kling / MiniMax）

**不再调用内置 VideoGen。前置条件：关2 样张已确认（全片默认 AI 生成随之生效）、关3 分镜已定，
且首帧已有公网 URL 或配好上传钩子**（`15-media-api.md` 第三节，这是换接口后唯一的新前置）。
满足就直接开跑。**"是否开始生成分段视频"这个问题不应存在**——它在关2/关3 已经答过了。

默认档位：`kling-video-v3` + `1080P` + `enable_audio=false` + `watermark=false`，`seconds=6`。
省钱档：`minimax-video-h3` + `768P`（要接受清晰度折损与可能残留的生成音轨）。

```bash
python scripts/media_api.py jobs --shots out/shots.json \
    --images-dir images --out-dir clips_raw --out work/video_jobs.json
python scripts/media_api.py batch --jobs work/video_jobs.json --concurrency 4
```

视频是**异步任务**：提交拿 `task_id` → 每 5 秒轮询 → 完成立刻下载（签名 URL 会过期）。
脚本会先把 `task_id` 写进 `<产物>.json` 侧车文件，**中断后用 `wait` 续等或重跑 batch，
绝不重新提交**——重复提交就是重复计费。`batch` 结束会汇总全部 `credit`。

全片沿用同一套材质语言：**每镜都「场景图 → 图生视频」**，不用静帧推拉凑镜、不混外部素材
（用户主动提供素材时另算；个别镜连崩才退 zoompan 兜底，见 `03-generation.md` 第四节）。
中途只在验收不过时动手，不回头征询。

提示词**只写运动**，机位默认锁死；`aspect_ratio` 只在文生视频时传，图生视频幅面由首帧决定。
**每镜抽首帧和末帧**核对四件事——静帧看不出来，只能靠这一步把关：

| 崩法 | 表现 |
|---|---|
| 主体变形 | 纸片融化、角色换脸 |
| 运镜跑偏 | 推过头把主体裁掉，或被拉远 |
| 纹理糊掉 | 纸纹变塑料、边缘发毛 |
| 亮度漂移 | 6 秒里越跑越亮，接下一镜像跳档 |

崩了就换备选提示词重出单镜，不要整批重来。

### ⑨ 片头 → `references/06-title-card.md`

单独一镜，单独一条路：无字载体场景 → 字库排字（`make_title.py`）→ 图生视频/推镜 → **验收** → 接回时间轴。

**歌名必须长在画面里，不许用 ASS 卡片。** 这是唯一一条"做错一定被打回"的规则。

**生成完必须跑验收，不过就重做（不设次数上限）：**

```bash
python scripts/check_title.py --clip clips/s01.mp4 --area 760,66,1160,622
```

查水印 / 时长 / 首字留白 / 占载体比 / 居中，退出码 2 就是不合格。
裁水印用 `scripts/crop_watermark.py`（先测后裁再复测，一条命令），**别手写 crop 值**。
**水印位置是浮动的**，不许套固定 crop 值——先 `--only watermark` 量出 bbox，再裁，再复测。
（真实事故：另一台机器生成时水印更靠右，按固定 110px 裁完留了半截，直接进了成片。）

**字不能交给生成模型。** 把已排字的静帧丢给图生视频，模型一定会重绘歌名（实测末帧整行消失）。
走「背景归模型、文字归图层」：无字场景生成运动 → PIL 静态文字层 → overlay 盖 N 帧。

**接回时间轴前先过切点匹配**，片头合格 ≠ 剪进去不刺眼：

```bash
python scripts/match_cut.py --a work/s01.mp4 --b work/s02.mp4 --outdir work/match
#   切点前 差 25.4 → 切点后 差 0.5  [通过]   判据：亮度差 ≤ 4
```

它只改两侧的出入口（A 尾巴加雾、B 开头拉焦），**帧数一帧不动**——叠化会吃掉重叠帧，
总帧一变字幕全部错位，所以不能用 xfade 解决切点问题。

### ⑩ 时间轴 / 拼接 / 混音 → `references/04-assembly.md`

帧是唯一真相；叠化要扣重叠帧；音频先出母版（-14 LUFS / TP ≤ -1.0）再挂。

### ⑪ 字幕 → `references/05-subtitles.md`

**不选"四个筐"，而是按画面推导一套配方。** 先读八个特征（明度/主色/材质/光向/密度/运动/年代/情绪），
再用 12 套配方做匹配打分，**top1 直接落地、top2 留档备选，不为字幕单独停一次**：

```bash
# 1) 手写一份画像（八个特征都要填）
python scripts/subtitle_router.py --profile out/sub_profile.json
# 2) 脚本给排名 + 命中理由 + 该用哪个脚本
```

字幕的观感随关4 的成片一起看；用户觉得不对，直接换备选 top2 重排，**不再重新打分、也不中途征询**。

同一部片里还要有**变奏**：副歌换载体或分离手段（每片 1–2 次）、桥段去掉载体留白（1 次）。
骨架（字体、字形、描边逻辑）全程不动。

**时序只有一条路**：`align_subs`（统一对齐 + 0.3s 硬门槛）→ `make_subs`/`make_subs_glow`（出 ASS）。
官方时间戳、歌词表、烧好的 ASS 都走同一个入口，不再有第二套参数：

```bash
python scripts/align_subs.py --audio song.m4a --lines out/lines.json \
    --out out/lines_sync.json --report out/sync_report.json --max-err 0.30 --strict
```

**任何字偏差 >0.3s 就返回 2，不许静默过关**；C 级句子脚本会逐条列出，人工听那几句。

**例外：能拿到官方 TTML（amll-ttml-db）就走逐字骨架，别用能量峰重排。**
官方 TTML 是每字一个 span 的逐字标注，比任何能量峰估计都可靠：

```bash
python scripts/realign_ttml.py --audio out/stems/htdemucs/song/vocals.wav \
    --ttml work/qrc/song.ttml --lines out/lines.json \
    --out out/lines_sync.json --report out/sync_report.json
```

两条硬规则：
- **先证同源**：用「逐句首尾字直接核对音轨强起音」确定偏移量，
  **不要用命中计数扫偏移**（离散指标会被量化带偏，本次偏了 65ms）。
- **验收用发声段**：字必须落在 F0 发声段内，落静音率 0 才算过。
  `scripts/eval_timeline.py` 用这个判据做横向评测。

改完时间轴**不要碰排版**：用 `scripts/land_timeline.py` 只更新
`times`/`start`/`end`/`cut` 四个时间字段，保留已定稿的 `shot`/`y`/`x`/`fs`/`accent`；
再用 `scripts/diff_ass.py` 确认 ASS 的样式与动画一字未动。
收尾用 `scripts/verify_final.py`（成片级自检）和 `scripts/final_check.py`（抽帧目视）。

详见 `references/04b-alignment.md` 第六之二节。

### ⑫ 质检 ══[关4]══

```bash
python scripts/quality_check.py out/final.mp4 --expect 1920x1080 --fps 24 --lufs -14
```

六项全过：规格 / 响度 / 黑帧 / 冻结帧 / 字幕越界 / **首帧亮度**。
首帧亮度是独立一项，**不受 `--ignore-head` 豁免**——黑帧检查默认豁免开头 1.6 秒，
而首帧黑正是 2 秒跳出的主因，必须单独拦。

再加人工四条：逐句查压主体、亮暗各抽两帧、375px 自检、**抽 0s/1s/3s 复核开场**。
375px 自检**必须覆盖开头三帧**（`references/05a-subtitle-layout.md` 第十节）：
首帧有没有内容、第 1 秒有没有在动的东西、第 3 秒能不能说出"这是一条什么视频"。

> 「开头是否静止/有没有钩子」**不写自动数值判定**：实测静态字牌的帧间像素差
> 比正常慢推镜头还高，数值分不出"无聊的静止"和"好看的慢推"，必须人看。

发布后的数据复盘（2s 跳出 / 5s 完播 / 完播率怎么归因）→ `references/14-douyin-review.md`。

### ⑬ 封面 + 发布文案 → `references/07b-cover-brief.md`、`references/11-copywriting.md`

**封面只按 `07b-cover-brief.md` 出**——那份《抖音系列封面标准化生图提示词 V2.0》是唯一依据，
构图、字体、字色、标题位置、质感、禁止项全部照它，不另立规则。
`07-cover.md` 只讲图出来之后怎么裁水印、怎么导出、怎么自检。

文案走**克制叙述法**：只讲作品的物理事实（材料/光/重复/消失），不讲感受；
零情绪词、不排比不对仗，正文用事实收（片长 + 歌手）。
评论引导单独写，可保留一个与剧情直接相关的具体问题，不泛泛问“好看吗”。
抖音标题 ≤20 字。**别在开头提 AI**——一提就把观众从"我的故事"拉回"别人的技术"。

### ⑭ 数据复盘回流 → `references/14-douyin-review.md`

发布后记录首段流失、平均观看、收藏、评论、主页访问和关注转化，先找最早的大流失点。
每次只改一个主变量，把结论写回下一首歌的 `douyin_brief.md`、L2-D 评分证据和分镜否决项。
完整版与独立预告分开评估；没有真实分段数据时只记录待补，不编造留存率。

---

## 三、打分机制（这个 skill 的核心）

三层，从粗到细。**每一层都是"多个候选 → 打分 → 淘汰 → 收敛"**，不是想到一个就用。

| 层 | 对象 | 候选 | 关键权重 | 门槛 |
|---|---|---|---|---|
| L1 | 视觉风格 | **5**（不同家族） | 情绪匹配 0.30、出图稳定 0.20 | <3.0 淘汰；≥4.5 标★推荐 |
| L2 | 剧情方案 | 3 套 | **钩子 0.20**、歌词咬合 0.20 | <3.0 淘汰 |
| L2-D | 抖音推流剧情 | 3 套 | 首帧钩子 0.25、留存曲线 0.20 | 命中否决项即停止 |
| L3 | 单镜提示词 | 每镜 2–3 条 | 主体 0.20、可生成 0.20 | 踩红线即出局 |
| L4 | 字幕配方 | 12 套里取 top1（top2 备选） | 明度 0.20 / 材质 0.18 / 情绪 0.16 | 分差<0.3 按可读性决胜 |

三条纪律：**同一轮一次评完**（标准不漂）、**每个分必须写证据**（写不出就是编的）、
**不许全员 5 分**（至少一项 ≤3）。

淘汰最多三轮：粗筛 → 定向改写最低维 → 定稿。**分差 ≤0.3 时按"可生成性"决胜**——
能出片的赢，好看的输。

完整评分卡、红线表、淘汰规则、JSON 格式见 `references/02-scoring.md`；
算术交给 `scripts/score_candidates.py`（它只算分和查规则，判断由你做）。

---

## 四、硬规矩（违反就一定出问题）

1. **不许手算时间戳**：所有 start/idx 来自工具回包或 timeline.json。
2. **不许凭肉眼判断素材规格**：分辨率/帧率/时长/音轨一律实测。
3. **单镜默认不超过 6 秒**：这是节奏要求，不是接口上限。网关支持 4–15 秒，
   真要拉长必须同步改 timeline 并写明理由，不能顺手把节奏拖垮。
4. **每一镜都要有备选**：没有备选时你会不自觉地"凑合"，凑合就是成片的上限。
5. **先出样张再批量**：3 张 vs 40 张，差 10 倍成本。
6. **片头歌名长在画面里**：不许用 ASS 标题卡压画面。
7. **字幕样式必须按画面推导**：用八特征给 12 套配方打分，**top1 直接落地、top2 备选**；
   禁止「暗调就用某一种」这种套法——那样所有片会撞款。
8. **字幕坐标逐句定**：躺姿/仰拍/人群镜头必压主体。
9. **封面只认 `07b-cover-brief.md`**：构图、字体、字色、标题位置、质感、禁止项全照它，
   不再有第二套版式说法。图出来之后才走 `07-cover.md`（裁水印 / 导出 / 自检）。
10. **字体必须显式加载**：`fontsdir` 绝对路径 + 转义盘符，缺字烧成豆腐块。
11. **并行生成用唯一前缀**：同名前缀会覆盖，丢过素材。
12. **音频先出母版再挂**：loudnorm 别塞进视频滤镜链。
13. **字幕逐字对齐，误差 ≤0.3s**：所有入口（含官方时间戳）都过 `align_subs`，
    超标返回 2；C 级句子必须人工听，不许靠调阈值放水。
14. **渲完必跑质检**：六项都过才算完（含首帧亮度）；成片 mtime 必须晚于字幕文件。
15. **交付前缩到 375px 看一眼**：1080p 上好看不代表手机上能读，且必须覆盖开头三帧。
16. **画幅固定 16:9；音频是完整原曲，不二次剪辑、不缩短、不拆条**：
    所有"砍前奏/拆条/缩片头"的优化一律不做，只改画面内容、顺序与信息密度。
17. **开场评交付文件不评分镜表**：片头做完要回到成片抽 0s/1s/3s 复核第 0–3 秒，
    首帧不黑、画面有动、有可读的概念字。
18. **每镜必须有推流任务**：缺 `traffic_role` / `change_type` 的镜头不得进入批量；仅换角度不算新信息。
19. **每 15–25 秒必须有效变化**：新信息、新关系、新后果或新目标，四选一，写不出来就改分镜。
20. **重复副歌必须升级**：用 `repeat_of + upgrade` 记录视角、关系、信息或后果变化，禁止纯重播。
21. **发布必须回流**：完整版与预告分开评估；评论问题只留一个具体的问题，不用“AI 制作”当开头卖点。
22. **关2/关3 通过后不再征询**：不问"是否全部用 AI 生成"，不问"是否开始生成分段视频"，
    不问"这一批出完继续吗"。一次点头覆盖后续执行，**只在关4 交片时收口**。
23. **生成一律走 `scripts/media_api.py`**：不再调用内置 ImageGen / VideoGen；
    图生视频首帧必须是公网 http(s) URL；提交结果不确定（502）时不许盲目重提，
    先查任务与积分，续等用 `wait`，重试用 `batch` 续跑。

---

## 五、交付清单

- [ ] `out/final.mp4` —— 分辨率/帧率/时长符合要求
- [ ] `out/timeline.json` —— 可复现，改字幕不必重出素材
- [ ] `out/score.json` —— 三层的候选与打分，能说清"为什么用这个方案"
- [ ] `out/narrative_report.json` —— 抖音分镜检查通过；首镜钩子、重复段升级、生产备选和验收字段齐全
- [ ] 响度 `-14 LUFS`，真峰值 ≤ `-1.0 dBTP`
- [ ] 质检六项全过（规格/响度/黑帧/冻结/字幕越界/**首帧亮度**）
- [ ] **开场复核**：抽 0s/1s/3s，首帧不黑、画面有动、有可读概念字
- [ ] **前奏 >8 秒时已按 `04a-timeline.md` 第 6 节填信息**，每 5 秒一次新信息逐段写得出
- [ ] 字幕逐句查过画面：人脸、手、乐器、道具、建筑中轴都没被压
- [ ] 亮处、暗处各抽两帧确认字幕没糊
- [ ] 片头歌名是画面的一部分；首字不贴载体边缘；抽首末帧没出画
- [ ] 片头接了第一镜且**切点亮度差 ≤ 4**（`match_cut.py`），抽 5 个点看过切点两侧
- [ ] **样张经用户确认**（关2），`style.md` 里留了确认记录；确认前没有开任何批量
- [ ] **关2 之后未就生成方式二次征询，关3 之后未就"是否开始出视频/继续下一批"提问**；
      全片每一镜都是「场景图 → 图生视频」，无整镜静帧凑数（个别连崩才 zoompan 兜底）
- [ ] **封面按 `07b-cover-brief.md` 出图**（不用第一帧），3:4 竖版；字数、形近字、多余物料逐条核过
- [ ] 375px 宽下字幕、封面标题都可读
- [ ] 发布文案按 `11-copywriting.md` 写：零情绪词、不排比、结尾用事实（抖音标题 ≤20 字）
- [ ] 成片 mtime 晚于字幕文件
- [ ] `out/douyin_review.json` —— 发布后记录最早大流失点、单一修改项与下一期回流规则；没有数据时明确待补

---

## 六、参考文档

| 文件 | 什么时候看 |
|---|---|
| `01-brief.md` | 拿到素材，要做分析和风格选择 |
| `02-scoring.md` | **每一层打分之前**（含红线表、淘汰规则、JSON 格式） |
| `03-generation.md` | 写提示词、批量出图出视频 |
| `15-media-api.md` | **出图/出视频前必读**：网关配置、四个模型可选参数、首帧公网 URL、费用与错误处理 |
| `04-assembly.md` | 拼时间轴、混音、渲染 |
| `04a-timeline.md` | timeline.json 字段规范；**前奏 >8 秒怎么填信息、最强镜前移、信息密度** |
| `04b-alignment.md` | 歌词对不齐、人声分离、起音校正 |
| `04c-ffmpeg.md` | 常用 ffmpeg 配方 |
| `05-subtitles.md` | **选字幕族、定参数** |
| `05b-subtitle-recipes.md` | **12 套字幕配方的完整参数**（载体/字形/动效/ASS 写法） |
| `05a-subtitle-layout.md` | 逐句落位、字号档、卡片像素级做法 |
| `06-title-card.md` | 做片头（**第〇节：片头就是交付文件第 0–3 秒**、载体选择、背景/文字分层、六个坑、切点匹配） |
| `07b-cover-brief.md` | **封面唯一依据**：抖音系列封面标准化生图提示词 V2.0（六大维度 + 固定 DNA + 禁止项） |
| `07-cover.md` | 封面出图之后的机械操作：裁水印 / 导出 / 自检（**不含设计规则**） |
| `11-copywriting.md` | **写发布文案**（克制叙述法：讲事实不讲感受、平台字数、反例对照） |
| `12-douyin-narrative.md` | **抖音推流叙事**：平台目标、首帧、前奏、全曲留存、重复段升级、互动与系列化 |
| `13-douyin-storyboard.md` | **双轨分镜卡**：推流任务 + 生成执行、字段规范与自动检查 |
| `14-douyin-review.md` | **发布后的数据复盘**：分段流失归因、单变量修改、结论回流 |
| `08-pitfalls.md` | 出问题先查这里（23 条实踩） |
| `09-style-library.md` | 31 套风格，选风格时翻 |
| `10-remotion.md` | 需要参数化模板/React 动效时才看 |

---

## 七、脚本速查

```bash
# 生成（第三方媒体网关，配置见 references/15-media-api.md）
python scripts/media_api.py models                       # 自检地址与 Key
python scripts/media_api.py image --prompt-file work/s07_image.txt --size 1920x1080 --out images/s07.png
python scripts/media_api.py edit --input images/s07.png --prompt "去掉右下角水印" --out images/s07_fix.png
python scripts/media_api.py video --prompt-file work/s07_motion.txt \
    --first-frame images/s07.png --seconds 6 --out clips_raw/s07.mp4
python scripts/media_api.py jobs --kind image --shots out/shots.json --out-dir images --out work/image_jobs.json
python scripts/media_api.py jobs --shots out/shots.json --out work/video_jobs.json
python scripts/media_api.py batch --jobs work/video_jobs.json --concurrency 4   # 断点续跑
python scripts/media_api.py wait --task-id <ID> --out clips_raw/s07.mp4         # 超时续等，不重提

# 分析
python scripts/mediainfo.py assets/ -o out/manifest.json
python scripts/song_structure.py --audio song.m4a -o out/structure.json
python scripts/beat_sync.py song.m4a -o out/beats.json
python scripts/style_advisor.py --audio song.m4a --lyrics lyrics.txt

# 打分
python scripts/score_candidates.py out/score.json --layer style|script|shot
python scripts/score_candidates.py out/score.json --layer douyin
python scripts/narrative_lint.py out/shots.json --production

# 字幕（时序只有一条路）
python scripts/align_subs.py --audio song.m4a --lines out/lines.json \
    --out out/lines_sync.json --report out/sync_report.json --max-err 0.30 --strict
python scripts/make_subs.py --lines out/lines_sync.json --beats out/beats.json --out out/subs.ass
python scripts/make_subs_glow.py --lines out/lines_sync.json --out out/subs_glow.ass \
    --sheet "images/s%02d.png" --recipe 02-window-glow
python scripts/place_subs.py

# 片头
python scripts/make_title.py --src images/plate.png --title "歌名" --singer "歌手" \
    --vertical --area x0,y0,x1,y1 --still out/title_still.png
python scripts/crop_watermark.py --src raw_title.mp4 --out clips/s01.mp4   # 先测后裁再复测
python scripts/check_title.py --clip clips/s01.mp4 --layout overlay       # 六项验收
python scripts/match_cut.py --a clips/s01.mp4 --b clips/s02.mp4 --outdir work/match  # 切点匹配
# 封面：按 references/07b-cover-brief.md 出图，图出来之后只需裁水印与导出

# 成片
python scripts/timeline.py build --manifest out/manifest.json --lines out/lines.json \
    --duration 209.08 --fps 24 -o out/timeline.json
python scripts/render_ffmpeg.py out/timeline.json -o out/final.mp4
python scripts/quality_check.py out/final.mp4 --expect 1920x1080 --fps 24 --lufs -14
```

字体在 `assets/fonts/`（MV Serif SC 衬线、站酷快乐体），Windows 下 `fontsdir` 要写
`D\:/绝对/路径`，别用相对路径。

---

## 八、工期

| 环节 | 用时 | 备注 |
|---|---|---|
| 风格样张 ×3（与用户迭代） | 5 分钟/轮 | 最多 3 轮 |
| 场景图（每镜 1 张） | 40 镜约 20 分钟 | 并发 4–8 |
| 图生视频（6s） | 40 镜约 60–90 分钟 | 逐镜抽首末帧验收 |
| 片头（图 + 视频 + 验收） | 15 分钟 | 不过就重做 |
| 封面（按 07b 直出 1 张） | 5 分钟 | 逐字核对 |
| **40 镜全片** | **2–4 小时** | 含重试 |

**工期按 2–4 小时报，不要报「几十分钟」**——重试是常态，不是意外。
**任何一环不合格就重做，不因为多花时间而接受次品。**

> 上表是旧内置工具的实测。切到第三方网关后，视频是**异步任务**：
> 提交很快，等待占大头，`batch` 可以并发等，所以实际工期以第一次实测为准，
> 成本以任务返回的 `credit` 汇总为准（`work/video_jobs.json.report.json`）。
