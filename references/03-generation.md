# 第三步：提示词与批量生成（图 → 视频）

这一步把"意象表"变成画面。分两段：先出**场景图**，再由场景图出**视频**。
每段都有固定的提示词结构，照结构写，别自由发挥。

---

## 一、先把分镜表定下来

```bash
python scripts/song_structure.py --audio song.m4a -o out/structure.json
```

规则（实测出来的，不是拍脑袋）：

| 段落 | 单镜时长 | 为什么 |
|---|---|---|
| 前奏 | 6–8s | 观众还在进来，慢一点留人 |
| 主歌 | 5–6s | 讲事情，镜头要留得住 |
| 预副歌 | 3.5–4.5s | 开始加速，为副歌铺垫 |
| **副歌** | **3–3.5s** | 切得密才有劲；重复段更要换景 |
| 桥 / 尾奏 | 6–8s | 落下来，给一个收束的画面 |

**单镜不超过 6 秒**——AI 视频单次生成的上限就是 6.04s，超过要靠慢放或拼接，都会露。

分镜表先给用户确认，再动图。表长这样：

| # | 起止 | 时长 | 歌词 | 画面（一句话） | 意象 |
|---|---|---|---|---|---|
| s01 | 0.0–5.9 | 5.9 | — | 夜巷纸幡，歌名进场 | 片头 |
| s08 | 44.7–48.6 | 3.9 | 固执的自转陀螺 | 陀螺在纸台面上高速旋转，顶光 | 陀螺 |

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

一次并发 **4–8 个** ImageGen 调用（不是 40 个）。原因：
- 太多会互相覆盖（见 `08-pitfalls.md` 第 1 条，同名前缀丢过素材）
- 分批出完就能分批检查，早发现风格跑偏

**每条提示词用唯一前缀**：`s07a_`、`s07b_`（镜号 + 候选号）。产物落进 `generated-images/`，
再按镜号归到 `images/s07.png`。

### 出图参数

| 项目 | 值 | 说明 |
|---|---|---|
| 尺寸 | `1536×1024`（16:9）/ `1024×1536`（3:4） | 按成片比例，别出方图再裁 |
| 质量 | high | — |
| 张数 | 每镜 1 张 | 候选靠"多条提示词"，不是"一条出多张" |

### 出图后必做的三件事

1. **裁水印**：ImageGen 在**右下角**，16:9 裁 `crop=1755:987:0:0`，3:4 裁 `crop=0,0,1024,1365`
2. **人工筛**：主体完整吗？有没有多余肢体？有没有蹦出文字？构图和分镜表一致吗？
3. **不合格换备选**，不要"凑合着用"——一帧凑合，整段视频都跟着凑合

---

## 四、图生视频

### 批量之后：逐镜抽首末帧，四件事一眼过

**静帧好看 ≠ 动起来好看。** 视频的崩法在图上一律看不出来，只能出完再验：

| 崩法 | 表现 |
|---|---|
| 主体变形 | 纸片融化、角色换脸 |
| 运镜跑偏 | 推过头把主体裁掉，或被拉远 |
| 纹理糊掉 | 纸纹变塑料、边缘发毛 |
| 亮度漂移 | 6 秒里越跑越亮，接下一镜像跳档 |

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
seconds    : 6        （单片上限 6.04s）
resolution : 1080P
audio      : false    （歌曲独立混音，不要生成音）
```

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
