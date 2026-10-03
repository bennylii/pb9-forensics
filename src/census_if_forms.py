#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剩余 if 通胀分型普查: 逐函数对比真源/反编译 if 数, 把多出的 if 按形态分类

用法: py -3 tools/census_if_forms.py [--samples 6] [--json tools/out/if_forms.json]
产出: 各形态占比 + 样例（每类贴具体代码行, 供 ParseIfMerge 补规则定靶）
"""
import os
import re
import sys
import json
import argparse
from collections import Counter, defaultdict

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from align_opcode_corpus import shudepb_bodies, decompiled_fns  # noqa: E402
import validate_pbd_names as V  # noqa: E402

SRC_DIR = os.path.join(ROOT, "software", "portalsrw")


def n_if(lines):
    return sum(len(re.findall(r"\bif\b", ln, re.I)) for ln in lines)


def classify_extra(dlines, tlines):
    """给反编译函数体的多余 if 定形态标签"""
    tags = Counter()
    depth = 0
    for ln in dlines:
        st = ln.strip()
        m = re.match(r"^if (.+?) then", st, re.I)
        if not m:
            continue
        cond = m.group(1)
        if " or " in cond.lower():
            tags["or_in_cond"] += 1
        elif cond.lower().startswith("not ") or " not " in cond.lower():
            tags["not_in_cond"] += 1
        elif re.search(r"\b(isvalid|isnull|isnumber)\b", cond, re.I):
            tags["builtin_cond"] += 1
        elif re.search(r"[<>](?!=)", cond):
            tags["cmp_cond"] += 1
        else:
            tags["plain_cond"] += 1
    return tags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=6)
    ap.add_argument("--json", default=os.path.join(ROOT, "tools", "out", "if_forms.json"))
    args = ap.parse_args()

    truth = V.load_truth()
    src_dirs = V.index_src_pbd(None)

    total_true = total_dec = 0
    tag_totals = Counter()
    samples = defaultdict(list)
    n_paired = 0

    for lib, objs in sorted(truth.items()):
        key = V.lib_key_normalize(lib)
        for src_dir in src_dirs.get(key, []):
            prefix = os.path.basename(src_dir).split("__")[-1].lower()
            by_obj = V.build_obj_index(src_dir, prefix)
            for objname, tinfo in objs.items():
                path = by_obj.get(objname.lower())
                if not path:
                    continue
                for libdir in (f"{lib}.PBD", f"{lib}.pbd", f"{lib}.PBL", f"{lib}.pbl", lib):
                    cand = os.path.join(SRC_DIR, libdir, f"{objname}.{tinfo['ext']}")
                    if os.path.exists(cand):
                        sb = shudepb_bodies(cand)
                        break
                else:
                    continue
                dec = dict(decompiled_fns(path))
                for fn, tbody in sb.items():
                    d = dec.get(fn)
                    if not d:
                        continue
                    n_paired += 1
                    ti, di = n_if(tbody), n_if(d)
                    total_true += ti
                    total_dec += di
                    if di > ti:
                        tags = classify_extra(d, tbody)
                        tag_totals.update(tags)
                        for t, c in tags.items():
                            if len(samples[t]) < args.samples:
                                idx = next(i for i, ln in enumerate(d)
                                           if re.match(rf"^\s*if .+? then", ln.strip(), re.I) and
                                           classify_key(ln, t))
                                samples[t].append((lib, objname, fn, d[max(0, idx-1):idx+4]))

    print(f"配对函数: {n_paired}  真源 if: {total_true}  反编译 if: {total_dec}  差: +{total_dec-total_true}")
    print(f"\n多余 if 形态占比（条件分类, 反编译侧全部 if 的构成）:")
    for t, c in tag_totals.most_common():
        print(f"  {t:14s} {c:6d}")
    for t, ss in samples.items():
        print(f"\n===== {t} 样例 =====")
        for lib, obj, fn, ctx in ss[:2]:
            print(f"-- {lib}/{obj}::{fn}")
            for ln in ctx:
                print("   ", ln[:96])
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump({"paired": n_paired, "if_true": total_true, "if_dec": total_dec,
                   "tags": dict(tag_totals)}, f, ensure_ascii=False, indent=1)
    print(f"\nOK -> {args.json}")
    return 0


def classify_key(ln, tag):
    st = ln.strip().lower()
    if tag == "or_in_cond":
        return " or " in st
    if tag == "not_in_cond":
        return st.startswith("if not ") or " not " in st
    if tag == "builtin_cond":
        return bool(re.search(r"\b(isvalid|isnull|isnumber)\b", st))
    if tag == "cmp_cond":
        return bool(re.search(r"[<>](?!=)", st))
    return not (" or " in st or " not " in st or re.search(r"\b(isvalid|isnull|isnumber)\b", st) or re.search(r"[<>](?!=)", st))


if __name__ == "__main__":
    sys.exit(main())
