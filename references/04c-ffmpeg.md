# ffmpeg 配方

本机若没有 ffmpeg，用隔离环境装一个自带版（不污染系统）：
```bash
python -m pip install imageio-ffmpeg
python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"
```
下文把该路径记作 `$FF`。

---

## 1. 出图后统一裁切（顺带切掉右下角平台角标）

```bash
$FF -y -i images/s01.png -vf "crop=1536:864:0:0,scale=1920:1080:flags=lanczos" images/c16/s01.png
```

裁切参数说明：原图 1536×1024，取上部 864 高 → 正好 16:9，且角标位于 y≈940 已被切掉。

---

## 2. 渲染基础时间线（无字幕无音轨）

先用 `make_timeline.py` 生成 `filter_base.txt`，再按 bounds 顺序把 clips 作为输入：

```bash
$FF -y -i clips/v01.mp4 -i clips/v02.mp4 -i clips/v03.mp4 \
    -filter_complex_script out/filter_base.txt -map "[out]" \
    -c:v libx264 -preset medium -crf 16 -pix_fmt yuv420p -r 24 -an out/base.mp4
```

---

## 3. filter_final.txt 模板（去角标 + 调色 + 烧字幕 + 混音）

```
[0:v]delogo=x=2:y=6:w=140:h=68,eq=contrast=1.05:saturation=1.04,vignette=a=PI/7,ass=subs.ass:fontsdir='D\:/<abs>/fonts',fade=t=in:st=0:d=1.2,fade=t=out:st=54.2:d=1.8,format=yuv420p[v];
[1:a]atrim=0:56.026,asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.0:LRA=11,afade=t=in:st=0:d=0.8,afade=t=out:st=53.4:d=2.6,aresample=44100[a]
```

- `delogo` 参数要先量角标 bbox：`$FF -i frame.png -vf "crop=280:140:0:0,scale=560:280:flags=neighbor,drawgrid=w=100:h=40:t=1:c=red@0.6"`
- `vignette=a=PI/7` 越大越强，默认 `PI/5`
- `loudnorm` 单遍会把采样率升到 96k，所以要跟 `aresample=44100`

---

## 4. 终渲

```bash
cd out   # 必须在此目录，filter 里用的是相对字幕路径
$FF -y -i base.mp4 -i song.mp3 -filter_complex_script filter_final.txt \
    -map "[v]" -map "[a]" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -r 24 \
    -c:a aac -b:a 192k -t 56.026 -movflags +faststart "成片.mp4"
```

**出片后立刻核对时间戳**（防渲到旧字幕）：
```bash
ls -la --time-style=+%H:%M:%S "成片.mp4" subs.ass
```

---

## 5. 逐帧读参考视频的卡拉OK字幕（定歌词时间最可靠的方法）

参考视频的字幕位置会变（有时在底部 y≈600-700，有时在顶部 y≈0-130），所以抓**上下两条字幕带**竖拼：

```bash
# 抽 2 秒一帧并拼接字幕带
for t in 34 36 38 40 42 44; do
  $FF -y -i ref.mp4 -ss $t -filter_complex \
    "[0:v]crop=1280:130:0:0[a];[0:v]crop=1280:120:0:600[b];[a][b]vstack" -frames:v 1 cap/c$t.png
done
$FF -y -i cap/c34.png -i cap/c36.png -i cap/c38.png \
    -filter_complex "[0:v][1:v][2:v]vstack=inputs=3" cap/sheet.png
```

一次读 6 帧就能还原整段换字时间。**比 ASR 和峰值检测都准。**

---

## 6. 封面

封面不做版式合成。设计与提示词一律按 `07b-cover-brief.md` 出图，出图后只需裁水印、导出，
步骤见 `07-cover.md`。这里不再提供任何封面版式的 ffmpeg 配方。

---

## 7. 验收用命令

```bash
# 规格
$FF -i 成片.mp4 2>&1 | grep -E "Duration|Stream #"

# 响度
$FF -hide_banner -i 成片.mp4 -af volumedetect -f null - 2>&1 | grep -E "mean_volume|max_volume"

# 抽帧（字幕区域横带）
$FF -y -i 成片.mp4 -ss 40 -filter_complex "[0:v]crop=1920:170:0:930" -frames:v 1 qa/f40.png

# 多帧拼一张联系表
$FF -y -start_number 1 -i qa/f%d.png -vf "scale=640:360,tile=2x3:padding=8:margin=8" -frames:v 1 qa/sheet.png
```

---

## 8. 音频偏移自检（怀疑音画不同步时先做这个）

用能量包络互相关判断音频是否真的偏移，避免误判：
```python
import numpy as np, subprocess, imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe(); sr, hop = 16000, 160
def dec(p):
    c=[FF,"-v","error","-i",p,"-f","f32le","-ac","1","-ar",str(sr),"-"]
    return np.frombuffer(subprocess.run(c,capture_output=True,check=True).stdout,dtype=np.float32)
def env(x):
    n=len(x)//hop; x=x[:n*hop].reshape(n,hop)
    e=np.sqrt((x**2).mean(axis=1)); return (e-e.mean())/(e.std()+1e-9)
a, b = env(dec("成片.mp4")), env(dec("song.mp3"))
best=(-9,0)
for lag in range(-300,301):
    x,y = (a[lag:], b) if lag>=0 else (a, b[-lag:])
    m=min(len(x),len(y)); c=float((x[:m]*y[:m]).mean())
    if c>best[0]: best=(c,lag)
print("lag = %+d0 ms  相关 %.3f" % best)
```
`lag=0` 且相关 >0.9 → 音频没问题，问题一定在**画面**（切点没对拍）。
