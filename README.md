# anim-mv · 动画 MV 制作 Skill

把一首歌做成一支动画风 MV：**先听歌推荐风格 → 定分镜 → 出图 → 图生视频 → 卡拍点剪时间线 → 逐字弹字幕 → 混音出片**。

A skill for turning a song into an animated music video: style recommendation from audio analysis, beat-synced storyboard, AI stills, image-to-video, timeline assembly and karaoke-style subtitles.

> 实测案例：周杰伦《等你下课》4 分 30 秒、47 个镜头、纸雕拼贴风，全片 1080p / 24fps。

---

## 它能做什么

| 环节 | 脚本 | 产出 |
|---|---|---|
| 听歌选风格 | `scripts/style_advisor.py` | BPM / 响度 / 明亮度 / 发音点密度 / 歌词意象 → 按契合度排序的 3 套风格 |
| 测拍点 | `scripts/beat_sync.py` | `beats.json`：BPM、相位 offset、1/8 拍网格 |
| 拆曲式报成本 | `scripts/song_structure.py` | 段落强度、建议单镜时长、**总镜数与预估 credits** |
| 卡拍点剪时间线 | `scripts/make_timeline.py` | xfade 脚本，切点自动吸附拍点，叠化中点压拍 |
| 逐字纸卡字幕 | `scripts/make_subs.py` | ASS 字幕，**逐句独立定位与字号**，一字一纸卡、衬线字、珊瑚高亮、可放大重音 |
| 出片 | 见 `references/ffmpeg-recipes.md` | delogo 去角标 + 调色 + 烧字幕 + loudnorm |

## 字幕是逐镜排的，不是固定一行

这是本 skill 和"自动生成字幕"最大的区别：**每句歌词的位置和字号都不一样**。

同一个片子里，人物可能站在画面中间、躺在画面底部、或者整幅都是人群，
一条固定高度的字幕必然会压到某几句的主体。所以流程是：
出完 `base.mp4` → 按每句中点抽帧 → 在帧上找空档 → 逐句写 `x`/`y`/`fs`。

```json
{"start":68.0,"end":73.0,"text":"躺在你学校的操场看星空","x":1250,"y":612,"fs":60,"accent":2}
{"start":113.0,"end":120.0,"text":"当你收到情书 也代表我已经走远","x":960,"y":104,"fs":58,
 "accent":1,"emph":{"13":1.4}}
```

装不下就降字号（66→60→58→56→52），横穿构图重心（钟楼、大门、对称特写）时
拆成左右两段。完整方法、字号对照表、落点选择与验收清单见
[`references/subtitle-layout.md`](references/subtitle-layout.md)。

### 卡片长什么样

这套卡片语法是照着一支参考 MV **逐帧量出来**的，不是拍脑袋定的：

| 项 | 值 | 项 | 值 |
|---|---|---|---|
| 纸面色 | `#F2E6CE` | 字色 | `#4A4244` |
| 高亮卡 | `#E7AA9C` + 米色字 | 投影 | `#968A7E`，偏移 4px |
| 倾斜 | ±2.8°（固定种子） | 纵向错落 | ±6px |
| 字间 | **−6px**（叠压） | 出现 | 缩放 88→100，80ms |

三个关键决定：**逐字出现**而不是整行淡入、**字体用宋体**而不是无衬线、
**一句里允许字号不统一**（`emph` 把关键字放大 1.3–1.5 倍）。
换掉任何一条，这套风格就散了。

## 8 套内置风格

`papercut` 纸雕拼贴 · `clay` 黏土定格 · `gouache` 水粉绘本 · `ink` 水墨留白 ·
`felt` 羊毛毡布偶 · `flatvector` 扁平矢量 · `glass` 彩绘玻璃 · `retroprint` 复古丝网

每套都给全了配色 hex、角色做法、可直接粘进生图模型的英文关键词、字幕样式与成本系数，
见 [`references/style-library.md`](references/style-library.md)。

风格不是随便挑的：脚本会算歌曲的速度区间、能量密度、频谱明亮度和歌词意象分类，
再和每套风格的适配区间打分。**先给结论，再让用户三选一**，不一次甩八个上去。

## 环境

```bash
python -m pip install numpy imageio-ffmpeg
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
```

`imageio-ffmpeg` 自带一份完整 ffmpeg（含 libx264 / libass / libfreetype / xfade / loudnorm），
系统里没有 ffmpeg 也能跑。要用 `ass` 烧字幕，ffmpeg 必须带 **libass**。

## 快速开始

```bash
# 1. 听歌 + 读词 → 三套候选风格
python scripts/style_advisor.py --audio song.mp3 --title "歌名" --lyrics lyrics.txt --json out/style.json

# 2. 定风格后取锁定参数（单镜时长 / 叠化 / 成本系数）
python scripts/style_advisor.py --audio song.mp3 --pick papercut

# 3. 测拍点
python scripts/beat_sync.py song.mp3 -o out/beats.json

# 4. 拆曲式，报总镜数与成本
python scripts/song_structure.py --audio song.mp3 -o out/structure.json

# 5. 排完分镜后剪时间线
python scripts/make_timeline.py --bounds 0,4.9,8.3,11.7 --beats out/beats.json \
    --total 56.026 --clip-len 6.04 --fade 0.5 --out out/filter_base.txt

# 6. 生成字幕
python scripts/make_subs.py --lines out/lines.json --beats out/beats.json \
    --font "ZCOOL KuaiLe" --out out/subs.ass
```

完整的十步流水线、参数速查、验收清单写在 [`SKILL.md`](SKILL.md)；
18 条踩坑记录（并行出图撞名、ASS 颜色是 BGR 倒序、fontsdir 必须绝对路径转义盘符、
字幕首字吸附偏向后方会累积成慢半拍、`-ss` 放 `-i` 前会让字幕静默不画……）见 [`references/pitfalls.md`](references/pitfalls.md)。

## 成本参考

单镜 ≈ 93 credits（1 张图 + 6 秒视频）。60 秒约 11 镜 ≈ 1000 credits；
4 分半约 47 镜 ≈ 4400 credits。开工前先报数，别让用户跑完才发现贵。

## 目录

```
SKILL.md                  十步主流程 + 参数速查 + 验收清单
scripts/                  风格推荐 / 测拍 / 拆曲式 / 时间线 / 字幕
references/               风格库、字幕布局、ffmpeg 配方、踩坑记录
assets/                   示例 json、字幕字体
```

## 用法（WorkBuddy / Claude Skill）

把整个目录放进 skills 目录（如 `~/.workbuddy/skills/anim-mv/`），
然后说「给《某首歌》做个动画 MV，歌词和 mp3 在这」即可。
也可以直接把 `SKILL.md` 的内容贴进对话让模型照着执行。

## 字体授权

仓库带了两款字体，都是 SIL Open Font License 1.1，可随本项目一起分发：

- `assets/fonts/MVSerifSC-SemiBold.ttf` —— 思源宋体（Noto Serif SC）SemiBold 固化实例，
  族名改为 `MV Serif SC`，避免和系统里的可变字体撞车。**默认字幕就用它。**
- `assets/fonts/ZCOOLKuaiLe-Regular.ttf` —— 站酷快乐体，圆润无衬线，做轻松题材时备选。
