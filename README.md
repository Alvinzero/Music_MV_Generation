# Music_MV_Generation · 从一首歌到一条能发的 MV

把一首歌（或一批素材）做成一支出得去的音乐 MV：**分析素材 → 选风格 → 出样张 → 写脚本 → 分镜 →
批量出图 → 图生视频 → 拼时间轴 → 定字幕 → 做片头 → 质检 → 出封面**。

An agent skill for turning a song into a publishable music video — with scoring gates, a
per-video subtitle language, and per-character lyric alignment.

> 由原来的 `anim-mv` 与 `video-finisher` 合并重构而来。前者偏"从零造素材"，后者偏"后期成片"，
> 现在是一条路：**先想清楚，再造素材，最后后期。**

---

## 这是什么

一个 **Agent Skill**，不是一个能双击运行的软件。`SKILL.md` 是主体（给 AI 读的工作流），
`references/` 是各环节的详细做法，`scripts/` 是可直接调用的工具。

核心信条两句话：

1. **AI 负责决策，工具负责精确**——时间值、规格、响度一律实测，不许模型估算。
2. **先做多，再做少**——每个关键选择都有候选、有打分、有淘汰，不是第一个想法就用。

---

## 主流程：13 步，四道关

```
①素材分析 → ②风格选项 ═关1═ → ③样张 ═关2═ → ④剧情方案 → ⑤分镜表 ═关3═
→ ⑥分镜提示词 → ⑦批量出图 → ⑧批量出视频 → ⑨片头 → ⑩时间轴/拼接
→ ⑪字幕 → ⑫质检 ═关4═ → ⑬封面交付
```

四道关都是**跟用户交互**，不是自己判断完就往下走：

| 关 | 用户看到什么 | 过关条件 |
|---|---|---|
| 关1 风格 | 5 个风格选项 + 推荐度 + 代价 | 明确选定一个主题 |
| 关2 样张 | 选定风格的 3 张静帧（特写 / 空镜 / 情绪） | 说"可以"才允许任何批量 |
| 关3 分镜表 | 镜头 ↔ 歌词对照表 | 确认后才写提示词 |
| 关4 终版 | 粗剪 / 成片 | 确认后才出封面 |

---

## 四个不太常见的机制

### 1. 三层打分 + 可生成性红线

| 层 | 对象 | 候选 | 最高权重 |
|---|---|---|---|
| L1 | 视觉风格 | 5 套（不同家族） | 情绪匹配 0.30 / 出图稳定 0.20 |
| L2 | 剧情方案 | 3 套 | **钩子 0.20** / 歌词咬合 0.20 |
| L3 | 单镜提示词 | 每镜 2–3 条 | 主体 0.20 / 可生成 0.20 |

配套**红线扣分**：手部特写 −1.5、画面内文字 −2.0、三人以上 −1.0、精细机械 −1.0。
淘汰最多三轮，分差 ≤0.3 时按"可生成性"决胜——**能出片的赢，好看的输**。

### 2. 字幕：12 套配方，按八个画面特征推导

不是"暗调就用暖光字"这种四选一。每部片先读八个特征（明度 / 主色 / 材质 / 光向 / 密度 / 运动 /
年代 / 情绪），再给 12 套配方打分取 top2。七维度定完（载体 / 字形 / 字色逻辑 / 分离手段 /
入场动效 / 排布 / 与画面的关系），一套样式才唯一。

```bash
python scripts/subtitle_router.py --profile out/sub_profile.json
```

### 3. 对齐：一套算法，逐字校到 0.3s

官方时间戳、歌词表、已烧录的 ASS 都走同一个入口，不再有第二套参数：

```bash
python scripts/align_subs.py --audio song.m4a --lines out/lines.json \
    --out out/lines_sync.json --max-err 0.30 --strict
```

任何一个字偏差超 0.30s 就返回 2。C 级句子会被逐条列出，必须人工听。

### 4. 片头与封面：字必须长在画面里

- **片头**：歌名不是字幕层。先出**场景**（不是一块广告牌），再版式排版——
  A 压字型（场景满幅、字压中部）或 B 纸带型（底部纸带承字），眉标/主标/细线/出处四件套。
  生成后必须过 `check_title.py`：水印、时长、留白、占宽、居中，不合格一律重做。
  接回时间轴前必须过 `match_cut.py`：片头合格 ≠ 剪进去不刺眼，切点亮度差要收到 ≤4。
  脚本强制上下各留 6.5%，手写按高度算满会把首字顶到纸边。
- **封面**：文字站中间、有载体。标题优先让 ImageGen 直出（逐字核对），核对不过才退字库合成。

---

## 仓库结构

```
SKILL.md                  主体：13 步流程、四道关、硬规矩 15 条、交付清单
references/
  01-brief.md             素材分析 → 意象表 → 风格选项 → 样张迭代
  02-scoring.md           三层打分机制（权重、红线、淘汰规则、JSON 格式）
  03-generation.md        七段式提示词、批量出图、图生视频与逐镜验收
  04-assembly.md          时间轴、拼接、混音、渲染
  04a-timeline.md         timeline.json 规范
  04b-alignment.md        字幕对齐（统一算法 + 0.3s 门槛）
  04c-ffmpeg.md           常用 ffmpeg 配方
  05-subtitles.md         字幕样式推导（七维度 + 八特征）
  05a-subtitle-layout.md  逐句落位、字号档、卡片像素级做法
  05b-subtitle-recipes.md 12 套字幕配方的完整参数
  06-title-card.md        片头（载体选择、背景/文字分层、六个坑、切点匹配）
  07-cover.md            封面（版式、直出核对）
11-copywriting.md      **发布文案：克制叙述法**（讲事实不讲感受、平台字数）             封面（直出核对清单、版式标准）
  08-pitfalls.md          27 条实踩的坑
  09-style-library.md     31 套视觉风格
  10-remotion.md          可选后端
scripts/                  26 个脚本（见下）
assets/fonts/             MV Serif SC（衬线）、站酷快乐体
assets/*.example.json     lines.json / beats.json 的字段示例
```

常用脚本：

| 脚本 | 干什么 |
|---|---|
| `mediainfo.py` / `song_structure.py` / `beat_sync.py` | 素材体检、曲式与镜数、拍点 |
| `style_advisor.py` | 31 套风格里出候选 |
| `score_candidates.py` | 按权重算候选分、标红线、排序 |
| `align_subs.py` / `align_core.py` | 统一对齐 + 逐字校对（0.3s 门槛） |
| `make_subs.py` / `make_subs_glow.py` | 出 ASS（有载体 / 无载体，后者支持 `--recipe`） |
| `subtitle_router.py` | 12 套字幕配方打分 |
| `make_title.py` / `make_cover.py` | 片头排字（压字/纸带两种版式）、封面合成 |
| `check_title.py` / `crop_watermark.py` | 片头验收（水印/时长/留白/居中）、一键裁水印并复测 |
| `match_cut.py` | 切点匹配：改两侧出入口（A 尾巴加雾 / B 开头拉焦），帧数不动，亮度差收到 ≤4 |
| `timeline.py` / `render_ffmpeg.py` / `quality_check.py` | 时间轴、渲染、质检 |

---

## 环境

```bash
python -m pip install numpy pillow scipy
```

还需要 **ffmpeg** 在 PATH 里（Windows 下 `fontsdir` 要写绝对路径 + 转义盘符）。
Python 3.10+。字体已随仓库附带，不需要额外下载。

---

## 三步试跑

```bash
# 1) 体检 + 曲式（先知道这首歌有多少镜、大概多少钱）
python scripts/mediainfo.py assets/ -o out/manifest.json
python scripts/song_structure.py --audio song.m4a -o out/structure.json

# 2) 出 5 个风格选项（不花 credits）
python scripts/style_advisor.py --audio song.m4a --lyrics lyrics.txt

# 3) 定好风格后，对齐字幕时间
python scripts/align_subs.py --audio song.m4a --lines out/lines.json \
    --out out/lines_sync.json --max-err 0.30 --strict
```

---

## 实测数据

| 项 | 数字 |
|---|---|
| 单镜成本 | ≈93 credits（图 8 + 6 秒视频 85） |
| 40 镜全片 | ≈3700 credits / 2–4 小时 |
| 字幕对齐（36 句 / 278 字） | 中位偏差 0.038s、p95 0.268s、最大 0.384s |
| 质检项 | 规格 / 响度 / 黑帧 / 冻结帧 / 字幕越界，五项全过 |

---

## 说明

这个仓库是工作流本身，不含任何歌曲、素材或成片。实际生成依赖 ImageGen / VideoGen 等外部能力，
脚本只负责"把参数算准、把时间对齐、把片子拼对"。
