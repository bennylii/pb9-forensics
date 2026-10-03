#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opcode 语料对齐: ShudePB 真源码函数体 <-> PbdViewer p-code 反编译渲染

对每个能按名配对的函数（含 create/destroy<->constructor/destructor 别名）:
  1. 统计反编译输出中未实现 opcode (`-------{op:XXXX}`) 的频次，
     并用 tools/pb-decompile 的 PB6 g_codes 表给候选语义
  2. 控制流关键字普查对照（if/for/choose/... 两边计数差 -> 结构化渲染缺口）
  3. 逐函数 token 相似度分布 + 最不相似样例
  4. goto 残留统计

用法:
  py -3 tools/align_opcode_corpus.py [--src-root src_pbd]
     [--json tools/out/opcode_corpus.json] [--md docs/21-opcode-corpus-report.md]
"""
import os
import re
import json
import sys
import argparse
from difflib import SequenceMatcher
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_pbd_names import (load_truth, index_src_pbd, lib_key_normalize,
                                build_obj_index)

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
G_CODES_PY = os.path.join(ROOT, "tools", "pb-decompile", "pbd", "pcode.py")
TRUTH_JSON = os.path.join(ROOT, "docs", "shudepb_truth.json")
SRC_DIR = os.environ.get("PB_TRUTH_DIR", os.path.join(ROOT, "truth_corpus"))

RE_BODY_START = re.compile(
    r"^\s*(?:(?:public|private|protected|global)\s+)*"
    r"(event|function|subroutine)\s+([^;\n]*);", re.IGNORECASE)
RE_BODY_END = re.compile(r"^\s*end\s+(function|event|subroutine)\s*;?\s*$", re.IGNORECASE)
RE_HEADER = re.compile(
    r"^(function|event)\s+([A-Za-z_]\w*)\s*\((.*)\)\s*(?:returns\s+(.+))?\s*$")
RE_OP_GAP = re.compile(r"-{7}\{op:([0-9A-Fa-f]{1,4})\}")
RE_TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
KEYWORDS = ["if", "else", "elseif", "for", "next", "do", "while", "loop",
            "choose", "case", "return", "goto", "try", "catch", "finally",
            "throw", "exit", "continue", "event", "post", "trigger"]
ALIAS = {"create": "constructor", "destroy": "destructor",
         "constructor": "create", "destructor": "destroy"}


def load_g_codes():
    """pb-decompile 的 PB6 opcode 表: {opcode_int: SM 名}"""
    if not os.path.exists(G_CODES_PY):
        return {}
    out = {}
    with open(G_CODES_PY, encoding="utf-8", errors="replace") as f:
        for ln in f:
            m = re.match(r"\s*\{'index':\s*(0x[0-9a-fA-F]+|\d+),\s*'name':\s*'(\w+)'", ln)
            if m:
                out[int(m.group(1), 0)] = m.group(2)
    return out


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("gbk", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def shudepb_bodies(path):
    """ShudePB 导出源码 -> {函数名小写: 代码行列表}"""
    lines = read_text(path).splitlines()
    bodies = {}
    in_fproto = False
    cur = None
    end_kind = None
    for ln in lines:
        st = ln.strip().lower()
        if st == "forward prototypes":
            in_fproto = True
            continue
        if in_fproto:
            if st == "end prototypes":
                in_fproto = False
            continue
        if cur is None:
            if st.startswith("//") or st.startswith("$pb"):
                continue
            m = RE_BODY_START.match(ln)
            if m:
                head = ln.split(";", 1)[0]
                toks = head.replace("(", " ").split()
                # 去掉 access/kind/type 前缀, 名字取 ( 前最后一个 token
                kind = m.group(1).lower()
                idx = [i for i, t in enumerate(toks) if t.lower() == kind]
                rest = toks[idx[0] + 1:] if idx else toks
                if "(" in head:
                    name = head.split("(", 1)[0].split()[-1]
                elif rest:
                    name = rest[-1]
                else:
                    continue
                if re.match(r"^[A-Za-z_]\w*$", name):
                    cur = []
                    end_kind = kind
            continue
        # 函数体内
        if RE_BODY_END.match(ln):
            key = name.lower()
            if key not in bodies or len(bodies[key]) < len(cur):
                bodies[key] = cur
            cur = None
            continue
        cur.append(ln)
    return bodies


def decompiled_fns(path):
    """反编译 .sr.txt -> [(name_lower, body_lines)]"""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    m = re.search(r"^// ===== Functions with p-code \(\d+\) =====$", text, re.MULTILINE)
    if not m:
        return []
    out = []
    cur_name, cur = None, None
    for ln in text[m.end():].splitlines():
        hm = RE_HEADER.match(ln)
        if hm:
            if cur_name is not None:
                out.append((cur_name, cur))
            cur_name, cur = hm.group(2), []
        elif cur_name is not None:
            cur.append(ln)
    if cur_name is not None:
        out.append((cur_name, cur))
    return out


def tokens(lines):
    return [t.lower() for t in RE_TOKEN.findall("\n".join(lines))]


def kw_census(lines):
    c = Counter()
    text = "\n".join(lines).lower()
    for kw in KEYWORDS:
        n = len(re.findall(rf"\b{kw}\b", text))
        if n:
            c[kw] = n
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-root", default=None)
    ap.add_argument("--json", default=os.path.join(ROOT, "tools", "out", "opcode_corpus.json"))
    ap.add_argument("--md", default=os.path.join(ROOT, "docs", "21-opcode-corpus-report.md"))
    ap.add_argument("--examples", type=int, default=3)
    args = ap.parse_args()

    truth = load_truth()
    src_dirs = index_src_pbd(args.src_root)
    g_codes = load_g_codes()

    op_gaps = Counter()            # opcode hex -> 次数
    op_gap_objs = defaultdict(set) # opcode -> 出现对象(最多记 200 个)
    kw_true = Counter()
    kw_dec = Counter()
    sims = []                      # (sim, lib, obj, fn)
    n_obj_pair = 0
    n_fn_pair = 0
    n_fn_total_dec = 0
    goto_dec = 0
    examples = []

    for lib, objs in sorted(truth.items()):
        key = lib_key_normalize(lib)
        for src_dir in src_dirs.get(key, []):
            prefix = os.path.basename(src_dir).split("__")[-1].lower()
            by_obj = build_obj_index(src_dir, prefix)
            for objname, tinfo in objs.items():
                path = by_obj.get(objname.lower())
                if not path:
                    continue
                # 找 ShudePB 源文件: portalsrw/<libdir>/<objname>.<ext>
                src_file = None
                for libdir in (f"{lib}.PBD", f"{lib}.pbd", f"{lib}.PBL", f"{lib}.pbl", lib):
                    cand = os.path.join(SRC_DIR, libdir, f"{objname}.{tinfo['ext']}")
                    if os.path.exists(cand):
                        src_file = cand
                        break
                if not src_file:
                    continue
                sb = shudepb_bodies(src_file)
                if not sb:
                    continue
                df = decompiled_fns(path)
                if not df:
                    continue
                n_obj_pair += 1
                dec_names = {n for n, _ in df}
                n_fn_total_dec += len(df)
                for name, body in df:
                    n = name.lower()
                    truth_name = n if n in sb else (ALIAS.get(n) if ALIAS.get(n) in sb else None)
                    if not truth_name:
                        continue
                    n_fn_pair += 1
                    t, d = sb[truth_name], body
                    dtxt = "\n".join(d)
                    for mo in RE_OP_GAP.finditer(dtxt):
                        code = mo.group(1).upper()
                        op_gaps[code] += 1
                        if len(op_gap_objs[code]) < 200:
                            op_gap_objs[code].add(f"{lib}/{objname}")
                    goto_dec += len(re.findall(r"\bgoto\s+\w+", dtxt))
                    kw_true.update(kw_census(t))
                    kw_dec.update(kw_census(d))
                    tt, dt = tokens(t), tokens(d)
                    if len(tt) < 4000 and len(dt) < 4000:
                        sim = SequenceMatcher(None, tt, dt, autojunk=True).ratio()
                        sims.append((sim, lib, objname, truth_name))
    sims.sort()
    out = {
        "objects_paired": n_obj_pair,
        "fns_paired": n_fn_pair,
        "fns_total_dec": n_fn_total_dec,
        "goto_in_decompiled": goto_dec,
        "op_gaps": {k: {"count": v, "sm_name": g_codes.get(int(k, 16)),
                        "sample_objs": sorted(op_gap_objs[k])[:8]}
                    for k, v in op_gaps.most_common()},
        "kw_true": dict(kw_true),
        "kw_dec": dict(kw_dec),
        "sim_buckets": {
            b: sum(1 for s, *_ in sims if b0 <= s < b1)
            for b, (b0, b1) in {"<0.3": (0, .3), "0.3-0.5": (.3, .5), "0.5-0.7": (.5, .7),
                                "0.7-0.85": (.7, .85), ">=0.85": (.85, 1.01)}.items()
        },
        "worst": [{"sim": round(s, 3), "loc": f"{l}/{o}:{f}"} for s, l, o, f in sims[:30]],
    }
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # markdown 报告
    md = []
    md.append(f"# 21. opcode 语料对齐报告（ShudePB 真源码 vs PbdViewer 反编译）\n")
    md.append(f"> 配对对象 {n_obj_pair}，配对函数 {n_fn_pair}/{n_fn_total_dec}，"
              f"goto 残留 {goto_dec}\n")
    md.append("> 注：1-3 节为工具重生成的基本表；多轮修复明细见文末手写节与 docs/22。\n")
    md.append("## 1. 未实现 opcode 频次\n")
    md.append("| opcode | 次数 | PB6 候选语义 (g_codes) | 样例对象 |")
    md.append("|--------|------|------------------------|----------|")
    for k, v in op_gaps.most_common(40):
        sm = g_codes.get(int(k, 16), "?")
        md.append(f"| 0x{k} | {v} | {sm} | {', '.join(sorted(op_gap_objs[k])[:3])} |")
    if not op_gaps:
        md.append("（无）")
    md.append("\n## 2. 控制流关键字普查（真源码 vs 反编译）\n")
    md.append("| 关键字 | 真源码 | 反编译 | 差 |")
    md.append("|--------|--------|--------|-----|")
    for kw in KEYWORDS:
        a, b = kw_true.get(kw, 0), kw_dec.get(kw, 0)
        if a or b:
            md.append(f"| {kw} | {a} | {b} | {b - a:+d} |")
    md.append("\n## 3. 逐函数 token 相似度分布\n")
    md.append("| 区间 | 函数数 |")
    md.append("|------|--------|")
    for b, v in out["sim_buckets"].items():
        md.append(f"| {b} | {v} |")
    md.append("\n## 4. 最不相似函数样例\n")
    for s, l, o, f_ in sims[:args.examples]:
        md.append(f"- {s:.3f} `{l}/{o}` :: {f_}")
    md.append("\n> 相似度基于 token 序列（去序噪声大），主要用于挑排查样本，不代表渲染质量总分。\n")
    with open(args.md, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"objects_paired={n_obj_pair} fns_paired={n_fn_pair}/{n_fn_total_dec}")
    print(f"op_gap_kinds={len(op_gaps)} op_gap_total={sum(op_gaps.values())} goto={goto_dec}")
    print(f"sim_buckets={out['sim_buckets']}")
    print(f"OK -> {args.json}")
    print(f"OK -> {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
