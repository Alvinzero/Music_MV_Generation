---
name: anim-mv
description: 为一首歌制作动画风 MV（时长不限，50 秒到数分钟），用户只需提供歌名、歌词和音乐 mp3，本技能先分析歌曲与歌词、推荐 3 套动画风格供选择，再走完整制作链路：拍点分析→分镜→出图→图生视频→卡点时间线→逐字字幕→混音→封面。当用户说"给某首歌做个 MV""做一个动画 MV 短片""仿照某个 MV 的风格""帮我推荐这种歌适合什么动画风格"时使用。
agent_created: true
---

# 动画 MV 短片

## 适用场景

- 用户给一首歌（歌名 + 歌词 + mp3），要做 50 秒到数分钟的动画 MV
- 需要先**推荐风格**再动手（本技能的核心差异点）
- 需要多镜头角色一致、歌词逐字弹出、镜头切换踩在拍子上
- 支持 16:9 横版 / 9:16 竖屏

不适用：真人实拍、需要口型对唱的片子。

## 开工只需三样东西

1. **歌名**
2. **歌词文本**（没有就用 ASR 从音频转，但要告知精度有限、必须让用户校对）
3. **音乐 mp3**

缺画幅信息时默认 16:9；缺角色设定时先按风格给一个原创角色方案让用户确认。

**成本**：单图 5–10 credits，每 5–6 秒视频 75–100 credits，**单镜约 93 credits**。
先用 `song_structure.py` 算出镜数再报价：60 秒约 11 镜≈1000 credits；3 分钟约 33–42 镜≈3000–3900 credits。
开工前必须告知总镜数与预估成本，并乘以所选风格的成本系数。

---

## Step 0（必做）：推荐风格

**不要跳过这一步直接出图。** 先跑分析，再让用户三选一。

```bash
python scripts/style_advisor.py --audio song.mp3 --title "歌名" \
    --lyrics lyrics.txt --json out/style.json
```

输出：BPM、响度、明亮度、发音点密度、歌词意象分类，以及**按契合度排序的前 3 风格**（带理由、建议节奏、字幕样式、成本系数）。

然后把前 3 名用 **AskUserQuestion** 呈现给用户，每个选项的 `description` 写清：

- 这套风格长什么样（一句话画面感）
- 为什么适合这首歌（引用打分理由 + 歌词意象）
- 建议单镜时长与叠化
- 成本系数

**不要只给风格名**，用户无法凭名字判断。也不要一次给 8 个——给 3 个。

用户选定后取锁定参数：

```bash
python scripts/style_advisor.py --audio song.mp3 --pick <style_id>
```

得到 `shot / fade / cost / subtitle`，后续时间线与字幕都按它来。

8 套风格的完整规格（配色 hex、角色做法、可直接粘的英文提示词、字幕建议、风险）
见 `references/style-library.md`。当前包含：

`papercut` 纸雕拼贴 · `clay` 黏土定格 · `gouache` 水粉绘本 · `ink` 水墨留白 ·
`felt` 羊毛毡布偶 · `flatvector` 扁平矢量 · `glass` 彩绘玻璃 · `retroprint` 复古丝网

---

## 主流程

### 1. 建工程目录

```
<project>/
├── images/  原画 1536x1024 + c16/ 裁好的 16:9
├── clips/   v01.mp4 …
├── out/     base.mp4 / subs.ass / beats.json / 成片
└── cover/   封面
```

### 2. 测拍点

```bash
python scripts/beat_sync.py song.mp3 -o out/beats.json
```

之后所有切点、字的出现时刻都吸附到 `offset + k × beat_period/8`。**不要凭感觉估 BPM。**

### 3. 定分镜

**先看时长。** 一分钟左右的短片按"一镜对应 1–2 句歌词"直接排；两分钟以上必须先分段，
否则镜头密度均匀铺开会很平。分段用：

```bash
python scripts/song_structure.py --audio song.mp3 -o out/structure.json
```

输出每段的主歌/副歌/桥段标记、强度、建议单镜时长与镜数，以及**总镜数与预估 credits**。
把这个数字报给用户再开工。

排镜原则：

- 每镜按所选风格的 `shot` 区间，**单镜不超过 6 秒**
- 副歌切得密（3–3.5s），主歌留得住（5–6s），前奏尾奏更长（6–8s）
- 副歌重复出现时，画面要**换景不换人**——同一动作换机位/换环境，避免观众看出重复
- 先把"镜头 ↔ 歌词"对照表给用户确认，再生成

### 4. 出图

- 尺寸 `1536x1024`，提示词写 `16:9 widescreen composition, subject centered`
- 固定提示词后缀 = `style-library.md` 里该风格的英文关键词，**每条原样带上**
- 每条都复用同一段"角色锁定描述"（形状/配色 hex/特征逐项列出）
- 需要"同一角色换场景"时用**图生图**：`image1` 传已有角色帧，提示词写
  `Keep the SAME characters with IDENTICAL designs … Now place them in a NEW scene`
- 出图后统一 `crop=1536:864:0:0` → `scale=1920:1080`（顺带切掉右下角平台角标）

### 5. 图生视频

每镜 6 秒 / `1080P` / `enable_audio=false`。
`negative_prompt` 必写：`morphing, melting, warping, distorting faces, extra limbs, photorealistic, 3D render, text, watermark`
提示词只描述**运动**，并强调保持该风格的材质（如 `keep flat layered paper crisp`）。

### 6. 搭时间线

```bash
python scripts/make_timeline.py --bounds 0,4.9,8.3,11.7 --beats out/beats.json \
    --total 56.026 --clip-len 6.04 --fade <风格 fade> --out out/filter_base.txt
```

脚本自动：吸附切点到拍点 → 叠化中点压拍（`offset = 拍点 − fade/2`）→ 超长镜头加慢放 → 输出 xfade 脚本。

### 7. 定歌词时间轴

优先级：**参考视频自带的卡拉OK字幕（逐帧读）> 用户给的时间表 > ASR**。
用户给的表常在后半段偏早、把两句并成一句，必须校对。
读法见 `references/ffmpeg-recipes.md` 的"逐帧读参考字幕"。

### 8. 生成字幕（逐字纸卡 + 逐镜定位）

```bash
python scripts/make_subs.py --lines out/lines.json --beats out/beats.json \
    --font "MV Serif SC" --out out/subs.ass
```

`lines.json` 每项：

```json
{"start":15.0,"end":18.0,"text":"你住的巷子里","x":800,"y":1010,"fs":66,"accent":0}
{"start":68.0,"end":73.0,"text":"躺在你学校的操场看星空","x":1250,"y":612,"fs":60,"accent":2}
{"start":113.0,"end":120.0,"text":"当你收到情书 也代表我已经走远","x":960,"y":104,"fs":58,
 "accent":1,"emph":{"13":1.4}}
{"start":68.0,"end":73.0,"text":"躺在你学校的操场看星空","x":960,"y":600,"fs":104,
 "mode":"scene","ink":[228,213,196],"edge":[10,43,82]}
{"start":1.0,"end":4.6,"text":"等你下课","x":960,"y":880,"fs":124,"title":true}
```

- `x` / `y` = **整行（长成之后）的中心点**；`fs` = 该句字号
- `accent` = 珊瑚色高亮卡的字下标（默认 0，`-1` 关闭）——**标该句的重点字，别无脑取首字**
- `emph` = `{字下标: 放大倍数}`，一句里允许字号不统一，用来做重音
- `tints` = **逐字换色**：`[{"from":4,"to":6,"paper":[238,214,170],"ink":[96,66,34]}]`
  唱到"灯亮"就让那两个字变暖光——词义驱动的最低成本做法，见 layout 第七节
- 片头是**独立版式**，不是字幕卡堆两排：`kind:"plate"`（整块纸底）+ `kind:"plain"`
  （无底文字，配 `ls` 拉开字距）+ `kind:"rule"`（细线分层级），见 layout 第七节
- `move` = **给字一条轨迹**：`{"d0":[0,0],"d1":[186,30],"frz0":-2,"frz1":16,"dur":1400,
  "t0":250.15,"fade":[80,520],"scale":0.44}`，配 `move_i:[12,13]` 只让这几个字动
- `carrier` = **让字本身变成物件**：目前内置 `balloon`（椭圆球体+气嘴+细绳），
  配 `carrier_fills` 逐字配色。载体模式会自动换成无底样式，纸卡不会盖住球
- `hold_end` = 只延长**显示**时长，不动逐字节奏——要给飘散留时间改这个，别改 `end`
- `mode:"scene"` = **字幕跟画面联动**：撤掉纸卡、字取画面主色、放大到 90–110 号、加描边。
  `ink` 是字色（取那块背景的**反色**），`edge` 是描边色（取背景主色）。
  **每分钟约一处，4 分半的歌用 4–5 次**，全落在"大词 + 开阔画面"的句子上；
  最能让观众记住的就是这几个瞬间，见 `references/subtitle-layout.md` 第七节
- 省掉 `x`/`y` 会退回 `place`(T/M/B) 兜底，只适合草稿

卡片语法（每字一张纸卡、衬线字、±2.8° 倾斜、纵向错落 ±6px、**字距 −6px 叠压**、
左端定死向右逐字生长、缩放 88→100 弹出 80ms）是照着一支参考 MV 逐帧量出来的，
参数表和量法都在 `references/subtitle-layout.md` 第六节，改样式前先读。

**字号是画面的一部分，不是常量。** 全片统一 84 号一定会压主体：
每个镜头主体位置不同，必须逐句找空档、按空档定位置、装不下就降字号（66→60→56→52），
横穿构图重心时拆成左右两段。完整方法见 `references/subtitle-layout.md`。

快速自检（只烧字幕、不重渲全片）：

```bash
# -copyts 必须加，否则时间戳从 0 重计，字幕滤镜什么都画不出来
ffmpeg -y -copyts -ss 71.5 -i out/base.mp4 \
  -vf "ass=out/subs.ass:fontsdir='D\:/abs/path/assets/fonts'" \
  -frames:v 1 qa/chk/c1.png
```

> 字体：默认给的是 `assets/fonts/MVSerifSC-SemiBold.ttf`（思源宋体 SemiBold 固化实例，
> 族名改成 `MV Serif SC` 以免和系统可变字体撞车）。换无衬线会让这套纸卡立刻失去印刷味。
> 换风格时同步调 `make_subs.py` 顶部的 `PAPER / INK / SHADOW / CORAL` 四组色。

### 9. 终渲

```bash
ffmpeg -y -i out/base.mp4 -i song.mp3 -filter_complex_script out/filter_final.txt \
  -map "[v]" -map "[a]" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -r 24 \
  -c:a aac -b:a 192k -t 56.026 -movflags +faststart "out/成片.mp4"
```

模板见 `references/ffmpeg-recipes.md`（delogo 去角标 + 调色 + 烧字幕 + loudnorm）。

### 10. 封面

选最有辨识度的一帧（主角完整、情绪正面），底部压纸带放片名，导出 1920×1080 PNG + 1280×720 JPG。

---

## 长片要点（2 分钟以上）

### 分批生成，别一口气排 40 个提示词

按段落分批，**每批 8–10 镜**：出图 → 抽帧确认 → 出视频 → 立刻 `cp` 到 `clips/vNN.mp4`。
一批做完再做下一批。一口气排满会出三个问题：撞名丢素材、中途发现角色跑偏要全部返工、上下文被大量返回值挤爆。

### 时间线仍用一条链，太长再在 fadeblack 处切

40 个输入对 ffmpeg 没问题，只是慢（4 分钟片子 base 渲染约 6–10 分钟）。
若嫌慢，在**本来就有 `fadeblack` 的转场**处切开，分两段渲染 base，再用 concat 拼接——
黑场是天然接缝，拼起来看不出来。普通 `fade` 处不能切。

```bash
# 两段 base 都是同规格编码，concat 时可直接 copy
printf "file 'base_a.mp4'\nfile 'base_b.mp4'\n" > list.txt
ffmpeg -y -f concat -safe 0 -i list.txt -c copy base.mp4
```

### 字幕文件会变长

40+ 句的 `lines.json`，靠脚本处理即可；但要注意：
- **每句的 `x`/`y`/`fs` 必须逐条排**，不能沿用上一句。方法是先出 `base.mp4`，
  再按每句中点抽帧、拼联系表，一屏 12 帧地过，边看边写坐标
- 主体躺在画面底部、仰拍建筑、人群全景这几类镜头最容易压人，单独标记出来返工
- 副歌重复时文本重复、时间不同，`lines.json` 里是**两条独立记录**，不要合并；
  但两遍副歌的画面不同，坐标也要分别给
- 全部排完先 `ass` 滤镜单帧抽查 6–8 张，再终渲，比渲完发现压脸再返工便宜得多

### 中途验收

每批出完抽 2–3 帧拼联系表看：主角是否完整、风格是否走样、有没有多出人物。
发现问题只返工那一批，成本可控。

---

## 参数速查

| 项 | 值 | 说明 |
|---|---|---|
| 出图尺寸 | 1536×1024 | 裁 1536×864 得 16:9 |
| 单镜实际时长 | 6.04s | 生成"6 秒"其实是 6.04s |
| 叠化 | 0.5s（或按风格） | `offset = 切点 − fade/2` |
| 慢放上限 | 2.5x | 超过改补拍 |
| 单镜成本 | ≈93 credits | 图 8 + 6s 视频 85 |
| 副歌单镜 | 3.0–3.5s | 切得密 |
| 主歌单镜 | 5.0–6.0s | 留得住 |
| 前奏/尾奏 | 6.0–8.0s | 可长镜 |
| 每批生成 | 8–10 镜 | 长片分批，出完即归档 |
| 纸卡字号 | 66 / 边距 16 | 卡 98px，1080p 手机可读 |
| 字号档位 | 66 / 60 / 58 / 56 / 52 | 空档小就降档，别硬塞 |
| 卡间距 | −6px | 负值叠压，才有手摆的质感 |
| 题字字号 | 120 / 边距 26 | 纸片 172px |
| 单行上限 | 12 字 | 13 字以上均分两段 |
| 字幕位置 | 逐句 `x`/`y` | 顶 96 / 中 420 / 底 1000 只是兜底默认值 |
| 重点字 | `accent` + `emph` | 珊瑚卡 + 1.3–1.5 倍放大 |
| 场景联动 | `mode:"scene"` | 撤卡、字取背景反色、放大到 90–110 号；每分钟约 1 处 |
| 字幕安全边 | 左右 30 / 上下 8 | 脚本自动回拉，别手动越界 |
| 响度 | -14 LUFS / -1 dBTP | loudnorm 单遍 |

## 踩坑速查（完整 16 条见 references/pitfalls.md）

1. 并行出图/出视频会因同名覆盖丢素材——每条提示词用唯一前缀
2. `output_dir` 参数会被忽略，产物落到 `generated-images/`、`generated-videos/`
3. `trim` 重置 frame_rate → xfade 报错；`fps`/`format`/`settb=AVTB` 必须放 trim 之后
4. ASS 颜色是 `&HAABBGGRR`（BGR 倒序）；`\1c/\3c/\4c` 用 `&HBBGGRR&`
5. `BorderStyle=3` 的 Outline 太深太厚会盖住纸面色
6. `ass=...:fontsdir=` 必须**绝对路径 + 转义盘符**，相对路径静默失效
7. 用 heredoc 拼 ASS 会被转义吃掉 `\a \f \r`——用写文件工具直接落盘
8. 渲染与字幕生成有竞态：出片前核对 mp4 的 mtime 晚于 subs.ass
9. 镜头按时长平均分配 → 中段字幕与画面错位；应按歌词时间轴分配
10. 首字吸附窗口偏向后方 → 每句都推后，累积成"慢半拍"
11. 长句要**均分**，不要按 12 硬切（会切出 8+2 的畸形尾段）
12. 远景/剪影不要放角色，宁可用空镜
13. 单镜过长先补拍，慢放只到 2.5x
14. 背影镜头也要写死发型，显式否定帽子/长发/双马尾
17. 全片套同一个字幕行位 → 躺姿/仰拍/人群镜头必压主体，必须逐句排 `x`/`y`/`fs`
18. `-ss` 放在 `-i` 前会让时间戳归零，字幕滤镜静默不画字——抽帧验字幕要加 `-copyts`
## 验收清单

- [ ] 风格是否已经过用户确认，出图后缀与所选风格一致
- [ ] 成片 mtime 晚于 subs.ass
- [ ] 切点在拍上：核对 filter 里 `offset + fade/2 = 拍点`，**别用 scene 检测验证**
- [ ] 字幕与参考原唱同帧的已唱字数一致
- [ ] **字幕逐句查过画面**：人脸、手、乐器、道具、建筑中轴都没被压
- [ ] **字幕有疏密变化**：不是全片同一个高度，位置跟着主体走
- [ ] **缩过字号的句子仍读得清**（1080p 下 ≥52）
- [ ] 每镜主角完整入画（头部、尾部）
- [ ] 单镜都 ≤6 秒
- [ ] 响度峰值 < -1 dBTP
