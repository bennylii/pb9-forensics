#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PbdViewer 反编译函数名 vs ShudePB 基准 验证器

用法:
  py -3 tools/validate_pbd_names.py                 # 报告到 stdout
  py -3 tools/validate_pbd_names.py --json out.json # 明细另存 JSON
  py -3 tools/validate_pbd_names.py --lib BQ_YZCL   # 只看某库

对每个 ShudePB 基准对象: 找到 src_pbd/<lib dir>/<LIB>__<obj>.sr.txt，
取 "// ===== Functions with p-code" 段的函数头名字，与基准名字集比对分类:
  match          名字在基准中（含 create/destroy <-> constructor/destructor 别名）
  anon           func_NNN
  sysname        被系统内建名顶替 (classname/postevent/...)，出现即错
  implicit       create/destroy 隐式构造/析构（基准不含，正常）
  mismatch       有名字但基准中没有（ShudePB 导出缺漏或 join 仍错）
"""
import os
import re
import json
import sys
import argparse
from collections import Counter

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
TRUTH_JSON = os.path.join(ROOT, "docs", "shudepb_truth.json")
SRC_PBD = os.path.join(ROOT, "src_pbd")  # 反编译输出根 (可被 --src-root 覆盖)

# PB 内部名 <-> 用户事件名别名
ALIAS = {"create": "constructor", "destroy": "destructor",
         "constructor": "create", "destructor": "destroy"}
# 用户代码不可能声明、出现即错的系统内建
SYSTEM_BUILTINS = {"classname", "postevent", "triggerevent", "typeof",
                   "getparent", "getcontextservice", "getclassdefinition"}

RE_PC_HEADER = re.compile(r"^(function|event)\s+([A-Za-z_]\w*)", re.MULTILINE)


def lib_key_normalize(lib):
    return re.sub(r"_(pbd|pbl)$", "", lib, flags=re.IGNORECASE).lower()


def load_truth():
    with open(TRUTH_JSON, encoding="utf-8") as f:
        return json.load(f)


def build_obj_index(src_dir, prefix):
    """目录内文件 <PREFIX>__<obj>.<类型后缀>.sr.txt -> {obj_lower: path}"""
    idx = {}
    pat = re.compile(rf"^{re.escape(prefix)}__(.+?)\.[a-z0-9]+\.sr\.txt$", re.IGNORECASE)
    for fn in os.listdir(src_dir):
        m = pat.match(fn)
        if m:
            idx.setdefault(m.group(1).lower(), os.path.join(src_dir, fn))
    return idx


def index_src_pbd(root=None):
    """src_pbd/<dir>/ -> {dir_last_segment_lower: [full_path,...]}"""
    root = root or SRC_PBD
    out = {}
    for d in os.listdir(root):
        p = os.path.join(root, d)
        if os.path.isdir(p):
            out.setdefault(d.split("__")[-1].lower(), []).append(p)
    return out


def parse_sr_txt(path):
    """返回 (pcode_fns:[(kind,name)], all_defs:[name])"""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    pcode, all_defs = [], []
    m = re.search(r"^// ===== Functions with p-code \(\d+\) =====$", text, re.MULTILINE)
    if m:
        pcode = [(k.lower(), n) for k, n in RE_PC_HEADER.findall(text[m.end():])]
    m = re.search(r"^// ===== All Function Definitions \(\d+\) =====$", text, re.MULTILINE)
    if m:
        seg = text[m.end(): text.find("// ===== Functions with p-code", m.end())
                   if "// ===== Functions with p-code" in text[m.end():] else len(text)]
        all_defs = [(k.lower(), n) for k, n in RE_PC_HEADER.findall(seg)]
    return pcode, all_defs


def classify(name, truth_names):
    n = name.lower()
    if re.match(r"^func_\d+$", n):
        return "anon"
    if n in truth_names:
        return "match"
    if n in ALIAS and ALIAS[n] in truth_names:
        return "match"
    if n in SYSTEM_BUILTINS:
        return "sysname"
    if n in ("create", "destroy"):
        # PB 为每个对象隐式编译构造/析构 p-code，基准(用户声明清单)不含，属正常
        return "implicit"
    return "mismatch"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="明细 JSON 输出路径")
    ap.add_argument("--lib", help="只报告指定库")
    ap.add_argument("--samples", type=int, default=5, help="每类示例条数")
    ap.add_argument("--src-root", default=None, help="替代 src_pbd 的反编译输出根目录")
    args = ap.parse_args()

    truth = load_truth()
    src_dirs = index_src_pbd(args.src_root)

    total = Counter()
    per_lib = {}
    details = []

    for lib, objs in sorted(truth.items()):
        if args.lib and lib.lower() != args.lib.lower():
            continue
        key = lib_key_normalize(lib)
        dirs = src_dirs.get(key, [])
        if not dirs:
            per_lib[lib] = {"error": "no src_pbd dir"}
            continue
        # 可能多目录同名（如 emr_advice 与 program__EMR__EMR_ADVICE），逐一验证
        for src_dir in dirs:
            prefix = os.path.basename(src_dir).split("__")[-1].lower()
            by_obj = build_obj_index(src_dir, prefix)
            stats = Counter()
            obj_rows = []
            for objname, tinfo in sorted(objs.items()):
                truth_names = set(tinfo["names"])
                path = by_obj.get(objname.lower())
                if not path:
                    stats["obj_missing"] += 1
                    continue
                pcode, _ = parse_sr_txt(path)
                row = {"lib": lib, "dir": os.path.basename(src_dir), "obj": objname,
                       "pcode_n": len(pcode), "truth_n": len(truth_names)}
                if not pcode:
                    stats["obj_no_pcode"] += 1
                    continue
                stats["objects"] += 1
                for kind, name in pcode:
                    cls = classify(name, truth_names)
                    stats[cls] += 1
                    if cls != "match":
                        obj_rows.append({"obj": objname, "cls": cls, "name": name})
                row["fns"] = [(k, n) for k, n in pcode]
                row["cls_summary"] = dict(Counter(classify(n, truth_names) for _, n in pcode))
                details.append(row)
            named = stats["match"]
            tot = sum(stats[c] for c in ("match", "anon", "sysname", "implicit", "mismatch"))
            stats["total_fns"] = tot
            stats["errors"] = stats["anon"] + stats["sysname"] + stats["mismatch"]
            lib_label = f"{lib} [{os.path.basename(src_dir)}]"
            per_lib[lib_label] = dict(stats)
            total.update(stats)

    print("=" * 78)
    print("PbdViewer 反编译函数名验证 (vs ShudePB 基准)")
    print("=" * 78)
    hdr = f"{'库 [目录]':38s} {'总':>6} {'正确':>6} {'隐式':>6} {'funcN':>6} {'系统名':>6} {'不匹配':>6} {'正确率':>7}"
    print(hdr)
    print("-" * 78)
    for lib, s in per_lib.items():
        if "error" in s:
            print(f"{lib:44s}  !! {s['error']}")
            continue
        tot = s.get("total_fns", 0)
        rate = f"{s.get('match',0)/tot*100:5.1f}%" if tot else "  n/a"
        print(f"{lib:44s} {tot:6d} {s.get('match',0):6d} {s.get('implicit',0):6d} "
              f"{s.get('anon',0):6d} {s.get('sysname',0):6d} {s.get('mismatch',0):6d} {rate:>7s}")
    print("-" * 78)
    tot = total.get("total_fns", 0)
    rate = f"{total.get('match',0)/tot*100:5.1f}%" if tot else "n/a"
    print(f"{'TOTAL':44s} {tot:6d} {total.get('match',0):6d} {total.get('implicit',0):6d} "
          f"{total.get('anon',0):6d} {total.get('sysname',0):6d} {total.get('mismatch',0):6d} {rate:>7s}")
    print(f"\n对象级: 缺文件={total.get('obj_missing',0)} 无pcode={total.get('obj_no_pcode',0)} 有pcode={total.get('objects',0)}")

    # 示例
    if args.samples:
        print(f"\n--- 非正确名示例 (每类最多 {args.samples} 条) ---")
        samples = {"anon": [], "sysname": [], "mismatch": []}
        for lib, objs in sorted(truth.items()):
            if args.lib and lib.lower() != args.lib.lower():
                continue
            key = lib_key_normalize(lib)
            for src_dir in src_dirs.get(key, []):
                prefix = os.path.basename(src_dir).split("__")[-1].lower()
                by_obj = build_obj_index(src_dir, prefix)
                for objname, tinfo in objs.items():
                    path = by_obj.get(objname.lower())
                    if not path:
                        continue
                    tn = set(tinfo["names"])
                    pcode, _ = parse_sr_txt(path)
                    for kind, name in pcode:
                        cls = classify(name, tn)
                        if cls in samples and len(samples[cls]) < args.samples:
                            samples[cls].append(f"{lib}/{objname}: {kind} {name}")
        for cls, items in samples.items():
            print(f"[{cls}]")
            for it in items:
                print(f"  {it}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"per_lib": per_lib, "total": dict(total), "details": details},
                      f, ensure_ascii=False, indent=1)
        print(f"\n明细 -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
