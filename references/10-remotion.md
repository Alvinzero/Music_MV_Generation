# Remotion 后端（可选）

> 默认后端是 ffmpeg。**只有下面这几条成立时才上 Remotion**，否则它只是多一层故障面。

## 什么时候值得用

| 用 Remotion | 用 ffmpeg |
|---|---|
| 同一版式批量换数据出 N 条 | 单条成片 |
| 需要逐帧精确的 React 动画、遮罩、3D、图表 | 只要烧字幕 + 叠化 + 混音 |
| 字幕卡/片头要反复改样式 | 字幕样式已经定型 |
| 客户要在浏览器里预览时间轴 | 交付只要一个 mp4 |

一条 5 分钟 1080p 的片子，ffmpeg 链路约 3–7 分钟渲完；Remotion 走 headless 逐帧，
通常在 10–30 分钟量级（取决于合成复杂度）。**复杂度换自由度，按需选。**

## 官方 Agent Skills（2026-10 现状）

```bash
npx skills add remotion-dev/skills
```

官方维护的一套 skill，供 Claude Code / Codex / Cursor 等 Agent 使用，包含：

| skill | 用途 |
|---|---|
| `/remotion-best-practices` | 总入口，不确定用哪个时先用这个 |
| `/remotion-create` | 新建工程或 composition |
| `/remotion-markup` | 写组件：布局、动画、排版、字体、时间 |
| `/remotion-studio` | 起 Studio 预览 |
| `/remotion-render` | 渲染成片或静帧 |
| `/remotion-captions` | 字幕与说明文字 |
| `/remotion-multimedia` | 音视频元数据、Mediabunny |

文档：`https://www.remotion.dev/docs/ai/skills`

## 与本 skill 的关系

**Remotion 是渲染后端，不是决策层。** 边界要划清楚：

```
timeline.json（唯一合同）
      │
      ├── render_ffmpeg.py   →  ffmpeg 直接出片
      └── remotion/          →  <Composition> 读同一份 timeline.json 渲染
```

两个后端吃**同一份 timeline.json**。换后端不改剪辑逻辑，这是这套架构的价值所在。

### 官方 Skills 源码要点（4.0.537，已读源码核对）

12 个 skill：`remotion-best-practices`（路由，其余都从它分流）/ `create` / `markup` / `studio` /
`render` / `captions` / `multimedia` / `maps` / `interactivity` / `saas` / `upgrade` / `docs`。

写法特点（值得抄的）：

- frontmatter 只有 `name` / `description` / `version`，**没有大段说明**
- 主 SKILL.md 是**路由**：一句话场景 + 相对链接 `[Remotion Markup](./remotion-markup/SKILL.md)`
- 细节全部下沉到同级 `.md`（`remotion-markup/` 下就有 30 多篇：transitions / sequencing /
  timing / audio / captions / measuring-text / video-editing …），按需加载
- 每篇都有 `name` / `description` / `metadata.tags`，便于检索

## 关键 API（源码里确认过的，不是猜的）

```tsx
import { Video, Audio } from "@remotion/media";      // 不是 <OffthreadVideo>
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { Composition, staticFile, useCurrentFrame } from "remotion";

<Video src={staticFile("clips/v01.mp4")}
       trimBefore={in_frame}          // 跳过素材开头
       durationInFrames={src}          // 取用多少源帧
       playbackRate={speed}            // <1 慢放
       objectFit="cover" />

<TransitionSeries>
  <TransitionSeries.Sequence durationInFrames={onScreen} />
  <TransitionSeries.Transition presentation={fade()}
      timing={linearTiming({ durationInFrames: 12 })} />
  <TransitionSeries.Sequence durationInFrames={onScreen2} />
</TransitionSeries>
```

- **`<Transition>` 不占额外时长**，它让相邻两镜交叠，总长 = Σ镜头 − Σ转场
- `<Composition calculateMetadata={...}>` 用来按 props 动态设 `durationInFrames / fps / width / height`
- 字幕类型：`Caption = { text, startMs, endMs, timestampMs, confidence, pageBreakAfter? }`
  （毫秒，不是帧）；已有 SRT 用 `parseSrt({ input })` 解析
- 渲染：`npx remotion render Film out.mp4 --props=props.json --codec=h264 --crf=18 --concurrency=4`
  单帧 `npx remotion still`，抽帧 `render --frames=0,30,90 --image-format=png`

## timeline.json → Remotion 的换算（本 skill 已实现）

| timeline.json | Remotion |
|---|---|
| `out_frame - in_frame` | `src`（源帧数） |
| `(out-in) / speed` | `Sequence.durationInFrames`（屏上帧数） |
| `speed` | `<Video playbackRate>` |
| `in_frame` | `<Video trimBefore>` |
| `xfade.frames` | `<Transition timing durationInFrames>` |
| `canvas.fps / width / height` | `calculateMetadata` 返回值 |
| `captions[].start_frame` | `frame` 直接比较（**不要转毫秒再转回帧**） |

## 响度：Remotion 不管这件事

Remotion 只负责画面和播放，**不做 loudnorm**。直接把原曲丢进去，成片响度就是源文件响度。
所以 `scripts/render_remotion.py` 会先用 ffmpeg 两遍 loudnorm 生成 `public/audio.m4a`，
再交给 `<Audio>` 播放。这一步不能省——否则换后端就等于换了一个响度。

## 模板已写好，可直接跑

`templates/remotion/` 里是可编译的工程：

```
src/types.ts          timeline.json 的类型
src/Root.tsx          Composition + calculateMetadata
src/Film.tsx          timeline → TransitionSeries + Video + Audio
src/CaptionLayer.tsx  纸卡字幕（与 ASS 版同一套版式参数）
```

```bash
cd templates/remotion && npm install      # 已装过就跳过
python scripts/render_remotion.py out/timeline.json -o out/final.mp4
python scripts/render_remotion.py out/timeline.json --studio   # 交互预览
```

`render_remotion.py` 会自动：素材硬链接进 `public/`、音频两遍 loudnorm、把绝对路径改写成
public 相对路径、生成 props、调 `npx remotion render`。

> 字幕卡这里用的是自写的 `CaptionLayer`，不是官方 `BasicCaptions` 元素。
> 因为 BasicCaptions 是"整行一个框 + 词级高亮"，而我们要的是"一个字一张纸卡"的版式。
> 如果哪天要换回官方元素，替换点在 `Film.tsx` 的 `<CaptionLayer />` 那一行。

## 国内网络：Chrome Headless Shell 下不来

Remotion 首次渲染会去 `storage.googleapis.com` 拉 chrome-headless-shell，国内**大概率
ECONNRESET**（本机实测重试两次后直接崩）。三条路，按推荐顺序：

1. **用本 skill 的脚本从镜像取**（最省事）

```bash
python scripts/fetch_chrome.py --version 157.0.8080.0
```

从 `registry.npmmirror.com` 的 chrome-for-testing 镜像下载（约 125MB，实测 3–6 分钟），
解到 `templates/remotion/.chrome/`。`render_remotion.py` 会自动发现并使用它。

2. **指向本机已有的 Chrome / Edge**

```bash
python scripts/render_remotion.py out/timeline.json --browser "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

⚠️ 实测 **Edge 不行**：能启动但立刻 `Closed with 0 signal: null`（Edge 157 + 当前
puppeteer-core 的组合）。要用就用真正的 Chrome，或者按第 1 条取 headless shell。

3. **给 Remotion 配代理**（有稳定代理时最干净），不做展开。

## 出片后必须统一色彩

Remotion 默认输出 **`yuvj420p`（全范围）**，而 ffmpeg 后端是 `yuv420p`（有限范围）。
两个后端混用时，画面会比 ffmpeg 版更亮更灰。

`render_remotion.py` 渲染完会自动跑一次归一化（`yuv420p + bt709`），默认开启，
嫌慢可以 `--no-normalize` 跳过。**换后端之前先想清楚这条要不要留。**

## 依赖落地位置（不要放 C 盘）

Remotion 后端有两个大件，**都放 D 盘**，C 盘只留代码：

| 件 | 位置 | 体积 |
|---|---|---|
| `node_modules` | `D:/workbuddy/runtime/remotion-node_modules` | 460MB |
| Chrome Headless Shell | `D:/workbuddy/runtime/chrome-headless-shell` | 283MB |
| npm 缓存 | `D:/workbuddy/runtime/npm-cache`（`npm config set cache`） | 451MB |
| ffmpeg | `D:/workbuddy/runtime/ffmpeg/ffmpeg.exe` | 84MB |

装依赖时不要直接在工程目录 `npm install`，按这个来：

```bash
cd templates/remotion
npm install                                  # 会装到本地 node_modules
# 然后搬到 D 盘并做目录联接（C 盘只留一个链接，不占空间）
python ../../scripts/relocate_deps.py
```

`relocate_deps.py` 会把 `node_modules` 移到 D 盘，并在原位置建 NTFS 目录联接（junction），
所以 `npx remotion` 仍然能正常解析依赖。`.chrome` 与 npm 缓存同理。

> **为什么用 junction 而不是符号链接**：Windows 的 symlink 需要管理员权限，
> junction 不需要，且对 Node 的模块解析完全透明。

脚本里的 ffmpeg 查找顺序已经把 `D:/workbuddy/runtime/ffmpeg/ffmpeg.exe` 放在第一位，
换机器时改这一处即可。

## 实测记录

- 依赖安装：`npm install` 260 个包，1 分 19 秒（npmmirror）
- 类型检查：`tsc --noEmit` 干净通过（remotion 4.0.537 + React 19）
- 渲染：264 帧 / 1920×1080 / 24fps，**51 秒**（concurrency=2，含首帧 bundle）
- 字幕：纸卡逐字弹出正常，珊瑚色重点字正常
- 与 ffmpeg 后端同一份 timeline.json，切后端只改一行命令


## 许可

Remotion 对个人与小团队免费；**较大商业组织需要购买公司授权**。落地前先确认使用主体，
别做到一半才发现许可问题。
