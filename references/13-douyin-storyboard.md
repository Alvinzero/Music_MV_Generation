# 抖音双轨分镜卡：推流任务 + 生成执行

> 每镜一张卡。先写推流任务，再写画面和提示词；缺任务的镜头不得进入批量生成。
> 字段同时供 `timeline.json`、`score_candidates.py` 与 `narrative_lint.py` 使用。

---

## 一、每镜必须回答两类问题

### 推流轨

- 这一镜让观众多知道了什么？
- 观众此刻为什么还要看下一镜？
- 它属于哪种任务：`hook / world / goal / escalation / turn / payoff / breath / comment / series`

### 生成轨

- 主体是什么，发生什么动作？
- 生图提示词、视频运动提示词、负向词分别是什么？
- 与上一镜怎么衔接，失败时换哪个备选？
- 首末帧按什么标准验收？

---

## 二、字段规范

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 镜号，如 `s01` |
| `start` / `end` | ✅ | 原曲绝对秒数；转 timeline 后仍以帧为准 |
| `dur` | ✅ | 槽位时长 = `end − start`，4–15s（>15s 拆镜，<4s 合法：生成按 4s 裁尾） |
| `seconds` | 生产模式 | 生成秒数，默认 `clamp(ceil(dur), 4, 15)`；只有「想从更长素材里挑一段」时才填更大值 |
| `lyrics` | 纯音乐可空 | 对应歌词，不修改原句 |
| `traffic_role` | ✅ | 推流任务，见上方枚举 |
| `audience_question` | hook/payoff/comment 必填 | 观众此刻的疑问或期待 |
| `change_type` | ✅ | `new_info / new_relation / new_consequence / new_goal / breath / payoff` |
| `visual` | ✅ | 一句话说清主体、动作、环境 |
| `camera` | ✅ | 锁死、横移、前推、后拉等，一镜一个方向 |
| `continuity` | ✅ | 与上一镜的空间、人物、光线和首尾帧关系 |
| `image_prompt` | 生产模式必填 | 七段式生图提示词 |
| `motion_prompt` | 生产模式必填 | 只写运动，不重新描述整个场景 |
| `negative` | 生产模式必填 | 至少包含 `text, watermark, logo` |
| `backup_prompt` | 生产模式必填 | 失败时可直接替换的备选 |
| `acceptance` | 生产模式必填 | 首末帧验收条目，至少 2 条 |
| `repeat_of` | 重复段必填 | 指向被重复的早期镜头或段落 |
| `upgrade` | 有 `repeat_of` 时必填 | 本次相比上次升级了什么 |

**时长怎么定**：按剧情单元定，不按段落平均切——同一段里「全景」和「转折」本来就该一长一短。
对照表与三条自检（一句话测试 / 「然后」测试 / 看得清测试）见
`12-douyin-narrative.md` 第 4.1 节。填完表先跑一遍 `narrative_lint.py --max-shot 15`。

---

## 三、示例

```json
{
  "id": "s01",
  "start": 0.0,
  "end": 4.8,
  "lyrics": "",
  "traffic_role": "hook",
  "audience_question": "纸做的校园会被雨毁掉吗？",
  "change_type": "new_info",
  "visual": "已建成的纸雕校园被第一滴纸雨击中，男孩和女孩被雨隔开",
  "camera": "locked-off",
  "continuity": "下一镜回到校园尚未遇雨的状态，保持同一建筑与角色位置",
  "image_prompt": "16:9 wide cinematic papercraft diorama, a school campus made of layered cut paper, first paper raindrop hitting the roof, two small paper figures separated by rain, visible paper fibre, deckled edges, cool grey light with a muted brick-red accent, no text, no watermark",
  "motion_prompt": "paper rain slowly becomes denser, roof paper edges begin to curl slightly, both figures remain still, camera locked, preserve the paper texture and composition",
  "negative": "text, letters, watermark, logo, extra characters, hand close-up, melting paper, plastic texture",
  "backup_prompt": "A paper book closing around a small paper flower, same palette and material, no text",
  "acceptance": [
    "首帧能同时识别纸城、雨和两个人物",
    "末帧建筑与人物没有变形，纸纹没有塑料感",
    "没有新增人物或画面文字"
  ]
}
```

---

## 四、写入顺序

1. 先填 `traffic_role / audience_question / change_type`
2. 再写 `visual / camera / continuity`
3. 用户确认分镜表后，补 `image_prompt / motion_prompt / negative / backup_prompt / acceptance`
4. 运行 `narrative_lint.py --production`
5. 通过后才允许批量出图

不要反过来先写 prompt，再补一个“钩子”标签。

---

## 五、自动检查

```bash
# 结构检查：字段、时长、首镜钩子、重复段升级
python scripts/narrative_lint.py assets/douyin_shot_card.example.json

# 生产前检查：额外检查提示词、备选和验收字段
python scripts/narrative_lint.py out/shots.json --production

# 严格模式：所有警告也视为失败
python scripts/narrative_lint.py out/shots.json --production --strict
```

退出码：`0` 通过，`2` 有错误，`1` 输入或文件结构错误。

---

## 六、与现有流程的关系

- 这些字段是**叙事与生成元数据**，不参与帧数计算。
- 转 timeline 时保留字段，渲染器忽略它们。
- 原有的 `in_frame / out_frame / start_frame / xfade / captions` 规则不变。
- 歌词逐字对齐、ASS、片头、封面和最终质检仍走原有流程。

**片头必须作为 `s01` 留在 `shots.json` 里，不要做成表外 prepend。**
片头就是交付文件的第 0–3 秒，只有它在镜头数组的第一位，
`narrative_lint.py` 的「首镜 `traffic_role` 必须是 `hook`」才管得住它。
否则会出现「分镜检查通过、成片开头仍是静态字牌」——评分对象又一次不等于交付对象。
（本片旧流程里 s01 本来就是片头，`render.py` 对 s01 单独取 `work/s01_title.mp4`，沿用即可。）
