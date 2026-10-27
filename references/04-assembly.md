# 第四步：拼成一条片子

素材（分镜片段 + 音频 + 字幕）齐了之后，这一段是纯工程。**规则只有一条：帧是唯一真相。**

秒是给人看的镜像；所有时间在 `timeline.json` 里以**整数帧**存储。
任何"大概 3.2 秒"的说法，最后都会在字幕对不上、音画差半拍上还回来。

---

## 一、时间轴

```bash
python scripts/timeline.py build --manifest out/manifest.json --lines out/lines.json \
    --duration 209.08 --fps 24 -o out/timeline.json
python scripts/timeline.py check out/timeline.json
```

规范见 `04a-timeline.md`。要记住的三点：

1. **总帧数 = 所有镜头帧数之和**（有叠化时，减去叠化重叠的帧）
2. **切点优先落在拍点上**（`beats.json`），不是均匀分配
3. 单镜槽位 ≤15s（接口 4–15s）。超了**拆镜**（拆点选歌词换行或动作间隙），不靠慢放——
   慢放只到 2.5x，再多就糊；槽位不足 4s 照排，生成按 4s、**裁尾**不裁头

---

## 二、拼接：硬切还是叠化

| 情况 | 选择 | 原因 |
|---|---|---|
| 同场景换机位 | **硬切** | 叠化会让观众以为时间过去了 |
| 换场景 / 换段 | 叠化 8–12 帧 | 过渡自然 |
| 亮度差很大的两镜 | **硬切** | 叠化会穿过灰，看着更脏 |
| 片头接正片 | **硬切** | 亮 → 暗本身就是"揭示" |

⚠️ **不要做"对黑"**（fade to black）。`quality_check.py` 会把中间的黑帧判成"非预期黑帧"，
整片不通过。要压亮度差，用硬切或者调色，不要用黑场。

⚠️ 叠化会缩短总长：`xfade` 的重叠帧要从总帧里扣掉，否则后面的字幕全部前移。

---

## 三、音频

**先出音频母版，再挂到视频上**，不要把 loudnorm 塞进滤镜链——两件事混在一起，
出问题查不出来。

```bash
# ① 量
ffmpeg -hide_banner -nostats -i song.m4a -af loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json -f null -

# ② 出母版（目标 -14 LUFS / TP ≤ -1.0）
ffmpeg -y -i song.m4a -t 209.083 \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11,volume=-1.7dB,afade=t=in:st=0:d=0.6,afade=t=out:st=206.48:d=2.6" \
  -ar 44100 -ac 2 -c:a pcm_s16le out/audio_master.wav

# ③ 复测，确认编码成 AAC 之后真峰值仍 ≤ -1.0 dBTP
ffmpeg -hide_banner -nostats -i out/audio_master.wav -af ebur128=peak=true -f null -
```

**源音频经常已经削顶**（本次实测 TP +2.18 dBTP）。这种情况线性 loudnorm 打不到 -14，
要用"dynamic loudnorm + 固定降 N dB"，再实测 AAC 编码后的真峰值，别信第一遍的数字。

---

## 四、字幕烧录（顺序不能乱）

```
lines.json ──align_subs──→ lines_sync.json（逐字时间 + 0.3s 门槛）
                                   │
                          make_subs / make_subs_glow ──→ subs.ass
                                   │
                            ffmpeg ass=… 烧进画面
```

- `align_subs.py`：**唯一**的时序入口。官方时间戳、歌词表、已烧录的 ASS 都走它，
  没过 0.3s 门槛就返回 2（详见 `04b-alignment.md`）
- `make_subs.py` / `make_subs_glow.py`：按 `lines_sync.json` 的 `times[]` 出声
- 下游一律引用 `lines_sync.json`，**不再碰原始 `lines.json`**（那是输入记录，不是真源）

⚠️ 字幕烧进画面后，改字 = 重编码视频。所以**先定字幕，再渲终版**。

---

## 五、渲染与质检

```bash
python scripts/render_ffmpeg.py out/timeline.json -o out/final.mp4
python scripts/quality_check.py out/final.mp4 --expect 1920x1080 --fps 24 --lufs -14
```

六项全过才算完：**规格 / 响度 / 黑帧 / 冻结帧 / 字幕越界 / 首帧亮度**。
首帧亮度独立检查，不受 `--ignore-head` 豁免（黑帧检查默认豁免开头 1.6 秒，
而首帧黑正是信息流 2 秒跳出的主因）。

再补四条人工检查（脚本查不了）：
- 字幕逐句看过画面：人脸、手、乐器、道具、建筑中轴没被压
- 亮处、暗处各抽两帧：字幕没有糊在背景里
- 缩到 375px 宽：字幕还能读，**且必须覆盖开头三帧**（0s/1s/3s）
- **开场复核**：首帧不黑、画面有动、有可读概念字（`06-title-card.md` 第〇节）

---

## 六、交付前最后一眼

```bash
ls -l --time-style=+%H:%M:%S out/final.mp4 out/subs_v2.ass
```

**成片时间必须晚于字幕文件**，否则你渲的是旧字幕（这个坑真的踩过）。

然后按 `SKILL.md` 的交付清单逐条过，最后做封面（按 `07b-cover-brief.md` 出图，处理见 `07-cover.md`）。
