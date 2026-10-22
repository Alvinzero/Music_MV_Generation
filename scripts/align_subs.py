#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字幕对齐的唯一入口：不管手上是官方时间戳、歌词表还是已烧录的 ASS，都走这一条。

    # A. 文本 → 逐字时间（官方时间戳/歌词表都走这里，一律重新校准）
    python align_subs.py --audio song.m4a --lines out/lines.json \
        --out out/lines_sync.json --report out/sync_report.json

    # B. 已烧录的 ASS → 只改 Start（文本/位置/色彩一个字节不动）
    python align_subs.py --audio song.m4a --ass out/subs.ass \
        --out out/subs_sync.ass --report out/sync_report.json

    # 硬门槛：任何一个字偏差 >0.30s 就返回 2
    python align_subs.py ... --max-err 0.30 --strict

算法只有一套（align_core）：HPSS 谐波 → 250–4200Hz → 4ms → 局部归一 → 峰 + DP。
"官方时间戳"也**不是免检**：它同样要过这一遍，偏差超标的句子会被单独列出来。
"""
import argparse
import io
import json
import sys

import numpy as np

import align_core as C
from retime_ass import parse_ass, group_by_end, fmt


def line_stats(nov, t, text, times, alt=None, delta_in=None):
    ref = [float(C.novelty_at(nov, t, [x], tol=0.045)) for x in times]
    ce = C.char_error(nov, t, times, alt, ref)
    errs = [c["err"] for c in ce if c["err"] is not None]
    weak = sum(1 for c in ce if c["weak"])
    max_err = max(errs) if errs else None
    grade = C.grade(max_err, weak / max(1, len(ce)))
    return dict(
        chars=[dict(i=i, ch=ch, t=round(times[i], 3),
                    peak=round(ce[i]["peak"], 3),
                    err=None if ce[i]["err"] is None else round(ce[i]["err"], 3),
                    err_peak=None if ce[i].get("err_peak") is None else round(ce[i]["err_peak"], 3),
                    err_alt=None if ce[i].get("err_alt") is None else round(ce[i]["err_alt"], 3),
                    weak=ce[i]["weak"]) for i, ch in enumerate(text)],
        max_err=max_err, weak=weak, grade=grade, delta_in=delta_in)


def run_lines(a, nov, t):
    items = json.load(open(a.lines, encoding="utf-8"))
    out, report = [], []
    for k, it in enumerate(items):
        text = it["text"]
        win = C.WIN_SCENE if it.get("scene") else C.WIN_SHOW
        r = C.align_line(nov, t, float(it["start"]), float(it["end"]), text, win)
        st = line_stats(nov, t, text, r["times"], r.get("alt"))
        rec = dict(it)
        rec.update(times=[round(x, 3) for x in r["times"]],
                   start_fit=round(r["times"][0], 3),
                   delta=round(r["times"][0] - float(it["start"]), 3),
                   win=win, fit=r["fit"], grade=st["grade"])
        out.append(rec)
        report.append(dict(i=k + 1, text=text, fit=r["fit"], reason=r["reason"],
                           start_in=float(it["start"]), start_out=round(r["times"][0], 3),
                           delta=rec["delta"],
                           max_err=None if st["max_err"] is None else round(st["max_err"], 3),
                           weak=st["weak"], n=len(text), grade=st["grade"],
                           chars=st["chars"]))
    return out, report, "lines"


def run_ass(a, nov, t):
    """ASS 重定时：只对齐实字层，按"起始间隔"分句，其余层跟随同样的位移。"""
    lines, evs = parse_ass(a.ass)

    def is_text(e):
        return e["layer"].replace("Dialogue:", "").strip() in ("2", "1", "")

    text_idx = [i for i, e in enumerate(evs) if is_text(e) and e["plain"].strip()]
    if not text_idx:
        text_idx = [i for i, e in enumerate(evs) if e["plain"].strip()]

    # 按起始时间排序，间隔 > 0.85s 视为新的一句
    text_idx.sort(key=lambda i: evs[i]["t0"])
    groups, cur = [], []
    for i in text_idx:
        if cur and evs[i]["t0"] - evs[cur[-1]]["t0"] > 0.85:
            groups.append(cur); cur = []
        cur.append(i)
    if cur:
        groups.append(cur)

    rep = []
    for idxs in groups:
        expect = np.array([evs[i]["t0"] for i in idxs], dtype=np.float32)
        lo, hi = expect[0] - C.SEARCH, min(t[-1], expect[-1] + C.SEARCH)
        pt, _ = C.peaks_in(nov, t, lo, hi, thr=C.THR_PEAK, sep=C.SEP)
        if len(pt) < len(expect):
            continue
        pick = C.dp_align(pt, expect)
        if pick is None or len(pick) != len(expect):
            continue
        pick = np.sort(pick)
        alt = C.greedy_align(nov, t, expect)
        for e, nt, at in zip([evs[i] for i in idxs], pick, alt):
            e["new"] = float(nt); e["alt"] = float(at)

        text = "".join(evs[i]["plain"][:1] for i in idxs)
        st = line_stats(nov, t, text, pick, alt)
        rep.append(dict(text=text, start_in=round(float(expect[0]), 3),
                        start_out=round(float(pick[0]), 3),
                        delta=round(float(pick[0] - expect[0]), 3),
                        max_err=None if st["max_err"] is None else round(st["max_err"], 3),
                        weak=st["weak"], n=len(text), grade=st["grade"], chars=st["chars"]))

    # 其它层（辉光/阴影）跟随同文本、同原始起点的位移
    shift = {round(e["t0"], 2): e["new"] - e["t0"] for e in evs if "new" in e}
    for e in evs:
        if "new" not in e and round(e["t0"], 2) in shift:
            e["new"] = e["t0"] + shift[round(e["t0"], 2)]

    for e in evs:
        if "new" in e:
            head = e["raw"].split(",", 9)
            head[1] = fmt(e["new"])
            e["raw2"] = ",".join(head)
        else:
            e["raw2"] = e["raw"]
    return lines, evs, rep


def summarize(rep, tag):
    errs = [r["max_err"] for r in rep if r["max_err"] is not None]
    amb = sum(1 for r in rep for c in r["chars"]
              if c.get("err_alt") is not None and c["err_alt"] > 0.30)
    amb_lines = [r["text"] for r in rep
                 if any(c.get("err_alt") is not None and c["err_alt"] > 0.30 for c in r["chars"])]
    chars = sum(r["n"] for r in rep)
    weak = sum(r["weak"] for r in rep)
    bad = [r for r in rep if r["grade"] == "C"]
    return dict(mode=tag, lines=len(rep), chars=chars,
                max_err=max(errs) if errs else None,
                p95_err=float(np.percentile(errs, 95)) if errs else None,
                median_err=float(np.median(errs)) if errs else None,
                weak_chars=weak, grade_C=len(bad),
                ambiguous_chars=amb, ambiguous_lines=amb_lines[:8],
                grade_A=sum(1 for r in rep if r["grade"] == "A"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--lines")
    ap.add_argument("--ass")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default="out/sync_report.json")
    ap.add_argument("--max-err", dest="max_err", type=float, default=0.30)
    ap.add_argument("--strict", action="store_true", help="超标返回退出码 2")
    a = ap.parse_args()
    if not a.lines and not a.ass:
        sys.exit("给 --lines 或 --ass")

    nov, t = C.analyze(a.audio)

    if a.lines:
        out, rep, tag = run_lines(a, nov, t)
        io.open(a.out, "w", encoding="utf-8", newline="\n").write(
            json.dumps(out, ensure_ascii=False, indent=1))
    else:
        lines, evs, rep = run_ass(a, nov, t)
        io.open(a.out, "w", encoding="utf-8", newline="\n").write(
            "\n".join(l if not l.startswith("Dialogue:") else
                      next(e["raw2"] for e in evs if e["raw"] == l)
                      for l in lines) + "\n")
        tag = "ass"

    s = summarize(rep, tag)
    s["max_err_limit"] = a.max_err
    s["pass"] = (s["max_err"] is not None and s["max_err"] <= a.max_err)
    io.open(a.report, "w", encoding="utf-8", newline="\n").write(
        json.dumps(dict(summary=s, lines=rep), ensure_ascii=False, indent=1))

    print("模式 %s  句 %d  字 %d" % (tag, s["lines"], s["chars"]))
    print("偏差：中位 %.3fs  p95 %.3fs  最大 %.3fs（门槛 %.2fs）"
          % (s["median_err"] or 0, s["p95_err"] or 0, s["max_err"] or 0, a.max_err))
    print("两种方法分歧 >0.3s 的字：%d 个（%d 句）"
          % (s.get("ambiguous_chars", 0), len(s.get("ambiguous_lines", []))))
    print("弱起音字 %d（%.1f%%）  A级 %d 句 / C级 %d 句"
          % (s["weak_chars"], s["weak_chars"] / max(1, s["chars"]) * 100,
             s["grade_A"], s["grade_C"]))
    print("写入 %s / %s" % (a.out, a.report))

    if not s["pass"]:
        print("\n[不通过] 有字的偏差超过 %.2fs，逐条看 --report 里的 grade=C" % a.max_err)
        for r in rep:
            if r["grade"] == "C":
                print("  · %-14s 最大 %.3fs 弱起音 %d/%d  %s"
                      % (r["text"][:12], r["max_err"] or 0, r["weak"], r["n"], r["reason"] if r.get("reason") else ""))
        if a.strict:
            sys.exit(2)
    else:
        print("[通过] 全部字落在 %.2fs 内" % a.max_err)


if __name__ == "__main__":
    main()
