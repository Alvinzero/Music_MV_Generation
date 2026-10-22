# timeline.json 规范

> AI 只负责**生成和修改这个文件**，渲染器严格按它执行。
> 只要这个合同稳定，改字幕样式不用重出素材，换渲染后端也不用改剪辑逻辑。

## 1. 为什么用帧，不用秒

`0.35s @ 30fps = 10.5 帧`。四舍五入到 10 还是 11 都说得通，但一路累下去就是"字幕慢半拍"。

所以：

- **一切时间以整数帧存储**（`*_frame`）
- 秒只做**镜像字段**（`*_sec`），仅供人读，**不许参与计算**
- 换算只在一处发生：`frame = round(sec * fps)`，由 `timeline.py` 统一执行

## 2. 字段

```json
{
  "version": 1,
  "canvas": {"width": 1920, "height": 1080, "fps": 24},
  "duration_frames": 7009,
  "duration_sec": 292.042,
  "audio": {
    "music": "song.m4a",
    "voice": null,
    "loudnorm": {"I": -14, "TP": -1.0, "LRA": 11},
    "fade_in_sec": 1.0,
    "fade_out_sec": 2.6
  },
  "video": [
    {"id": "s01", "file": "clips/v01.mp4",
     "in_frame": 0, "out_frame": 144,
     "start_frame": 0, "start_sec": 0.0, "dur_sec": 6.0}
  ],
  "captions": [
    {"text": "这风铃 跟心动很接近",
     "start_frame": 251, "end_frame": 360,
     "chars": [{"c": "这", "f": 251}, {"c": "风", "f": 264}],
     "x": 960, "y": 946, "fs": 66, "accent": 0}
  ]
}
```

### video[]

| 字段 | 含义 |
|---|---|
| `file` | 素材路径 |
| `in_frame` / `out_frame` | **素材内部**取用区间（帧） |
| `start_frame` | 在**成片时间轴**上的起点（帧） |
| `xfade` | 与**前一镜**之间的转场：`{"type":"fade","frames":12}` |

三个坐标的关系：

```
start_{i+1} = start_i + (out_i - in_i) - xfade_i+1
```

`xfade` 记在**后一个镜头**上。`frames: 0` 表示硬切（用 concat）。

### captions[]

| 字段 | 含义 |
|---|---|
| `text` | 显示文本（可含空格作为停顿标记，渲染时忽略） |
| `start_frame` / `end_frame` | 整句显示区间 |
| `chars` | 逐字出现时刻，**每个字一个 f**，必须严格递增 |
| `x` / `y` | 整行长成后的**中心点**（不是左上角） |
| `fs` | 该句字号，允许逐句不同 |
| `accent` | 高亮字的下标，`-1` 关闭 |

## 3. 校验规则（`timeline.py check`）

**错误**（必须修）：

- 素材文件不存在
- `out_frame <= in_frame`
- 相邻镜头衔接不等于 `start_i + dur_i - xfade`
- 字幕 `end_frame <= start_frame`
- 字幕起点超出片长
- `chars` 时间不递增

**警告**（可接受但要知情）：

- 字幕重叠（两条的显示区间相交）
- 叠化帧数超过相邻镜头长度

## 4. 常见错误

| 症状 | 原因 |
|---|---|
| 字幕整体比画面慢半拍 | 某处用秒算了一遍再转帧，误差累积 |
| 转场处画面跳一下 | `xfade` 记在了前一个镜头上 |
| 尾段黑屏 1 秒 | 素材总长比音频短，没有用 `tpad` 补帧 |
| 声音比画面早结束 | 视频用了 `-t`，音频没跟同一个时长 |

## 5. 与动画 MV（本 skill）的衔接

本 skill 产出的是 `shots.json`（每镜 start/end 秒）。转成 timeline 时用：

```bash
python timeline.py build --cuts out/cuts.json --fps 24 --duration 292.01 \
    --audio song.m4a --lines out/lines.json -o out/timeline.json
```

`cuts.json` 就是 `[{"file":"clips/v01.mp4","start":0,"end":5.35}, ...]`（秒），
脚本负责按同一处换算成帧。
