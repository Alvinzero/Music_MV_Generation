#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐条对比新旧 ASS：确认只有时间变，样式与动画参数一字未动。

比对维度：
  ① 样式行（Style:）必须完全一致
  ② 每个 Dialogue 的**文本与全部 override tag** 必须完全一致
     （只允许 Start/End 两列变化）
  ③ 统计时间位移量
"""
import io
import re
import sys


def parse(path):
    head, events = [], []
    for ln in io.open(path, encoding="utf-8"):
        ln = ln.rstrip("\n")
        if ln.startswith("Dialogue:"):
            parts = ln.split(",", 9)
            events.append((parts[0], parts[1], parts[2], parts[3], parts[9]))
        else:
            head.append(ln)
    return head, events


def ts(s):
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def main():
    a_path, b_path = sys.argv[1], sys.argv[2]
    ha, ea = parse(a_path)
    hb, eb = parse(b_path)

    print("=== 样式/头部 ===")
    if ha == hb:
        print("✅ 完全一致（%d 行）" % len(ha))
    else:
        print("⚠ 有差异：")
        for x, y in zip(ha, hb):
            if x != y:
                print("  旧: " + x)
                print("  新: " + y)
        if len(ha) != len(hb):
            print("  行数不同 %d vs %d" % (len(ha), len(hb)))

    print("\n=== 事件 ===")
    print("  数量：旧 %d / 新 %d" % (len(ea), len(eb)))
    if len(ea) != len(eb):
        print("⚠ 事件数不同")
        return
    style_bad = text_bad = 0
    shifts = []
    for (la, sa, ea_, sty, txa), (lb, sb, eb_, styb, txb) in zip(ea, eb):
        if sty != styb:
            style_bad += 1
        if txa != txb:
            text_bad += 1
            if text_bad <= 3:
                print("  文本/标签不同：\n    旧 %s\n    新 %s" % (txa, txb))
        if sa != sb or ea_ != eb_:
            d0 = ts(sb) - ts(sa)
            d1 = ts(eb_) - ts(ea_)
            shifts.append((d0, d1))
    print("  样式列不同：%d" % style_bad)
    print("  文本/override 标签不同：%d" % text_bad)
    if shifts:
        d0 = [s[0] for s in shifts]
        d1 = [s[1] for s in shifts]
        print("  Start 位移：均 %+.3f  范围 %+.3f ~ %+.3f"
              % (sum(d0) / len(d0), min(d0), max(d0)))
        print("  End   位移：均 %+.3f  范围 %+.3f ~ %+.3f"
              % (sum(d1) / len(d1), min(d1), max(d1)))
        print("  位移非零的事件：%d / %d" % (len(shifts), len(ea)))
    else:
        print("  时间完全未变（异常）")


if __name__ == "__main__":
    main()
