#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把新版逐字时间轴落地到 lines_sync.json / lines_sub.json。

## 为什么不重跑 build_subs.py

build_subs.py 用 `ln["start"]` 选镜号，镜号决定落位（top/bottom）。
当用户明确要求**排版（落上/落下）不得改动**时，
就不能重跑落位判据，而是：

  保留 lines_sub 里已定稿的 shot / y / x / fs / accent / emph
  只更新 times / start / end / cut 这四个**时间**字段

## 字段语义（与 subs_tool.emit 一致）

  times[i]  第 i 个字的点亮时刻
  start     底板(SH 柔影)出现时刻 = 首字时刻 − lead
  end       收字时刻 = 尾字时刻 + tail
  cut       下一句的 start；本句所有字在此前统一收掉

lead / tail 沿用上一版相对首尾字的偏移量，clamp 到合理范围，
这样字幕的"起—收"节奏与已看过的版本一致，只是整体平移到正确位置。

## 用法

```bash
python land_timeline.py --new out/lines_sync_new.json \
    --sub-old out/lines_sub_prev.json \
    --sync-out out/lines_sync.json --sub-out out/lines_sub.json
```
"""
import argparse
import io
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", default="out/lines_sync_new.json")
    ap.add_argument("--sub-old", default="out/lines_sub_prev.json")
    ap.add_argument("--sync-out", default="out/lines_sync.json")
    ap.add_argument("--sub-out", default="out/lines_sub.json")
    ap.add_argument("--lead-min", type=float, default=0.0)
    ap.add_argument("--lead-max", type=float, default=0.35)
    ap.add_argument("--tail-min", type=float, default=0.30)
    ap.add_argument("--tail-max", type=float, default=1.80)
    a = ap.parse_args()

    new = json.load(io.open(a.new, encoding="utf-8"))
    sub = json.load(io.open(a.sub_old, encoding="utf-8"))
    assert len(new) == len(sub), "句数不一致"

    out_sub = []
    for i, (nw, so) in enumerate(zip(new, sub)):
        nz = [k for k, c in enumerate(nw["text"]) if c.strip()]
        o_nz = [k for k, c in enumerate(so["text"]) if c.strip()]
        assert nz == o_nz, "第 %d 句的字位不一致" % i

        n_times = [float(nw["times"][k]) for k in nz]
        o_times = [float(so["times"][k]) for k in o_nz]

        # 沿用旧版相对偏移
        lead = o_times[0] - float(so["start"])
        tail = float(so["end"]) - o_times[-1]
        lead = min(max(lead, a.lead_min), a.lead_max)
        tail = min(max(tail, a.tail_min), a.tail_max)

        rec = dict(so)              # 保留 shot/y/x/fs/accent/emph/fit 等
        rec["times"] = list(nw["times"])
        rec["start"] = round(n_times[0] - lead, 3)
        rec["end"] = round(n_times[-1] + tail, 3)
        rec["fit"] = "landed"
        out_sub.append(rec)

    # cut = 下一句 start
    for i in range(len(out_sub) - 1):
        out_sub[i]["cut"] = float(out_sub[i + 1]["start"])
    out_sub[-1].pop("cut", None)

    # 落位合法性检查
    problems = []
    for i, r in enumerate(out_sub):
        nz = [k for k, c in enumerate(r["text"]) if c.strip()]
        ts = [r["times"][k] for k in nz]
        if abs(ts[0] - r["start"]) > 0.36:
            problems.append("句%d 首字与 start 偏差 %.3f" % (i, ts[0] - r["start"]))
        if r["end"] - ts[-1] > 1.85:
            problems.append("句%d end 超出尾字 %.3f" % (i, r["end"] - ts[-1]))
        for u, v in zip(ts, ts[1:]):
            if v <= u:
                problems.append("句%d 时间非递增 %.3f→%.3f" % (i, u, v))
            if v - u > 1.6:
                problems.append("句%d 字间隔 %.3f" % (i, v - u))
        if r.get("cut") is not None and ts[-1] >= r["cut"]:
            problems.append("句%d 尾字越过下一句 cut" % i)
    for j in range(len(out_sub) - 1):
        nzs = [k for k, c in enumerate(out_sub[j + 1]["text"]) if c.strip()]
        tnext = out_sub[j + 1]["times"][nzs[0]]
        if out_sub[j]["times"][-1] >= tnext:
            problems.append("句%d 尾字越过句%d 首字" % (j, j + 1))

    json.dump(out_sub, io.open(a.sub_out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    sync_out = [dict(r) for r in out_sub]
    for r in sync_out:
        r.pop("shot", None); r.pop("y", None); r.pop("x", None)
        r.pop("fs", None); r.pop("accent", None); r.pop("cut", None)
    json.dump(sync_out, io.open(a.sync_out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("写入 %s（%d 句）" % (a.sub_out, len(out_sub)))
    print("写入 %s（%d 句）" % (a.sync_out, len(sync_out)))
    if problems:
        print("\n⚠ 问题 %d 条：" % len(problems))
        for p in problems:
            print("  " + p)
    else:
        print("\n✅ 时间轴自检通过：无越界、无非递增、无跨句冲突")


if __name__ == "__main__":
    main()
