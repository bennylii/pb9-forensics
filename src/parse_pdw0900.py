#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDW0900 (.dwo) 直解: 从 PBD 的 DataWindow 编译二进制提取列定义+code table

容器层用 pbl_util（PBD=PBL 格式），条目层扫 [len4=strlen+1][GBK文本][00] 流。
流元素类型（WDW_SHARE 配对实测定案）:
  短名      'yysx'                — 表列名（也可能是控件名）
  dbname    'emr_yzb.yysx'        — 表.列 权威归属
  code table '长期\\t1/临时\\t2/...' — PB 码表语法原文（display[tab]data, 行间 '/'）

用法:
  py -3 tools/parse_pdw0900.py --pbd <path>            # 单库
  py -3 tools/parse_pdw0900.py --all                   # 全语料
产出: docs/dw_sem_<LIB>.json  {dwname: {columns:[{name,dbname,values}], sql}}
"""
import os
import re
import json
import sys
import struct
import argparse

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "pbl-dump"))
import pbl_util  # noqa: E402

# 码表语法: 行=display[tab]data, 行间 '/'; 首行 display 可为空; 可有尾部空行
# 例: '长期\t1/临时\t2/急诊\t3/带药\t4/\t0/' ; '\t1/\t0/' ; '已记费\t1/已提交\t/'
RE_CODETABLE = re.compile(
    r"^[^\t/]{0,12}\t[^\t/]{0,24}(?:/[^\t/]{0,12}\t[^\t/]{0,24})*/*$")
RE_DBNAME = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_]\w*$")
RE_IDENT = re.compile(r"^[A-Za-z_]\w*$")
RE_INT = re.compile(r"^-?\d+$")
RE_EXPR = re.compile(r"^[^\t(/]{0,24}[(=]")


def _rows(s):
    return [r for r in s.split("/") if r != ""]


def is_codelike(s):
    """真码表: 语法匹配 + 每行 data(右侧) 不含括号/等号 (排除校验表达式)。
    data 可以是数字/字母/空/null/CJK 词 (如 cxbz00 的 Z/+/−, cyztlx 的 治愈/好转)。
    """
    if not RE_CODETABLE.match(s):
        return False
    has_ct = False
    for row in _rows(s):
        if "\t" not in row:
            continue
        has_ct = True
        dat = row.split("\t", 1)[1]
        if "(" in dat or "=" in dat:
            return False
    return has_ct


def is_validation(s):
    """校验表达式串: display[tab]表达式, 表达式含 ( 或 ="""
    if not RE_CODETABLE.match(s):
        return False
    for row in _rows(s):
        if "\t" in row and RE_EXPR.match(row.split("\t", 1)[1]):
            return True
    return False


def scan_strings(blob):
    """线性扫 [len4][printable-GBK+\\t\\r\\n][00] 流 -> [(pos, text, endpos)]"""
    out = []
    n = len(blob)
    pos = 0
    while pos < n - 8:
        ln = struct.unpack("<I", blob[pos:pos+4])[0]
        ok = False
        # 上限放宽到全 blob: SQL 等长串也是 len 前缀存储, 不放宽会把游标逼脱轨
        if 1 <= ln <= max(n, 65536):
            seg = blob[pos+4:pos+4+ln]
            if seg.endswith(b"\x00"):
                txt = seg[:-1]
                if txt:
                    printable = all(b in (9, 10, 13) or 32 <= b < 127 or b >= 0x81 for b in txt)
                    if printable:
                        try:
                            out.append((pos, txt.decode("gbk"), pos + 4 + ln))
                            pos += 4 + ln
                            ok = True
                        except Exception:
                            pass
        if not ok:
            pos += 1
    return out


def scan_strings_utf16(blob):
    """PDW1100 (PB10+/Unicode) 的串流: [len4=字节数含2B终止符][UTF-16LE 文本][00 00]"""
    out = []
    n = len(blob)
    pos = 0
    while pos < n - 8:
        ln = struct.unpack("<I", blob[pos:pos+4])[0]
        ok = False
        if 4 <= ln <= max(n, 65536) and ln % 2 == 0:
            seg = blob[pos+4:pos+4+ln]
            if seg.endswith(b"\x00\x00"):
                txt = seg[:-2]
                if txt:
                    chars = []
                    printable = True
                    for k in range(0, len(txt), 2):
                        v = int.from_bytes(txt[k:k+2], "little")
                        if v in (9, 10, 13) or 32 <= v < 127 or 0x4E00 <= v <= 0x9FFF or 0x3000 <= v <= 0x303F or 0xFF00 <= v <= 0xFFEF:
                            chars.append(v)
                        else:
                            printable = False
                            break
                    if printable:
                        try:
                            s = "".join(map(chr, chars))
                            out.append((pos, s, pos + 4 + ln))
                            pos += 4 + ln
                            ok = True
                        except Exception:
                            pass
        if not ok:
            pos += 1
    return out


def extract_sql(blob):
    """PB9: 裸 SELECT...; PB11: PBSELECT( VERSION(400) TABLE(...) COLUMN(...)...)"""
    m = re.search(rb"SELECT", blob)
    if m:
        seg = blob[m.start():]
        cut = len(seg)
        for i, b in enumerate(seg):
            if b < 0x20 and b not in (9, 10, 13):
                cut = i
                break
        return seg[:cut].decode("gbk", errors="replace")
    m = re.search(rb"PBSELECT\x00\x00\x00", blob)
    if m:
        seg = blob[m.start() + 12:]
        cut = len(seg)
        for i in range(0, len(seg) - 1, 2):
            v = int.from_bytes(seg[i:i+2], "little")
            if v == 0 or (v < 0x20 and v not in (9, 10, 13)) or v > 0xFFFD:
                cut = i
                break
        return seg[:cut].decode("utf-16-le", errors="replace")
    return ""


def parse_dwo_strings(items):
    """字符串流 -> 列记录 {dbname: {name, values:[]}}

    规则（WDW_SHARE/BQ_YZCL 配对实测定案）:
    1. 点号 dbname 'A.B' -> 新列记录; 名字 = 其前 ≤12B 的裸标识符(若为列名)
    2. 裸标识符紧随(≤12B)另一裸标识符 -> 裸 dbname 列记录 (如 pzfs/pzfs, ccolor/color)
       （args 的 ':X'+'X' 对因带冒号被标识符检查排除）
    3. 码表语法串 -> 归最近的列记录 (不论距离; 中间的二进制/初始值串不影响)
    """
    cols = {}
    last_ident = None    # (text, endpos) 上一个裸标识符
    last_col = None      # 最近的列 key
    for pos, s, endp in items:
        if is_validation(s):
            # 校验表达式串: display[tab]表达式 -> 归最近列的 validation
            if last_col:
                cols[last_col].setdefault("validation", s)
            continue
        if is_codelike(s):
            if last_col:
                cols[last_col]["values"].append(s)
            continue
        if RE_DBNAME.match(s):
            name = last_ident[0] if (last_ident and pos - last_ident[1] <= 12) else ""
            cols.setdefault(s, {"dbname": s, "name": name, "values": []})
            last_col = s
            last_ident = None
            continue
        if RE_IDENT.match(s) and len(s) <= 40:
            if last_ident and pos - last_ident[1] <= 12:
                # 裸 dbname (紧随另一裸标识符, 允许同名字对 如 pzfs/pzfs)
                key = f"@{s}"
                if key not in cols:
                    cols[key] = {"dbname": s, "name": last_ident[0], "values": []}
                last_col = key
                last_ident = None
            else:
                last_ident = (s, endp)
            continue
        # 其他串 (数字/文本/格式) 不打断 last_col 的码表归属链;
        # 重置 last_ident (数字/带括号串不是列名)
        last_ident = None
    return cols


def iter_entries(pbd_path):
    """统一条目迭代: 按 HDR 魔数分发 — 'P\\x00' = Unicode(1024B 头) 走 unicode_pbl;
    ASCII 'PowerBuilder' 走 pbl_util (ANSI)。Unicode 库不能用 pbl_util 试解:
    条目能读出但名字是 latin-1 乱码, 会以垃圾抢先返回。

    yield (name, raw_bytes)  — raw 已剥注释前缀
    """
    with open(pbd_path, "rb") as f:
        head = f.read(64)
    if head[4:6] == b"P\x00" and head[6:8] == b"o\x00":
        import unicode_pbl
        entries = unicode_pbl.read_entries(pbd_path)
        for ent in entries:
            raw = unicode_pbl.entry_data(pbd_path, ent)
            if ent.commentlen and raw[:7] != b"PDW0900" and raw[:7] != b"PDW1100":
                raw = raw[ent.commentlen * 2:]
            if ent.commentlen and raw[:7] != b"PDW0900" and raw[:7] != b"PDW1100" and len(raw) > ent.commentlen:
                raw = raw[ent.commentlen:]
            yield ent.name, raw
        return
    for unicode in (False, True):
        try:
            nods = pbl_util.extract_nods(pbd_path, unicode)
        except Exception:
            nods = None
        if nods and any(nod.entries for nod in nods):
            for nod in nods:
                for ent in nod.entries:
                    try:
                        data = pbl_util.extract_data_from_entry(pbd_path, ent)
                    except Exception:
                        continue
                    raw = "".join(x[-1][: x[-2]] for x in data).encode("latin-1", errors="replace")
                    if ent.commentlen:
                        raw = raw[ent.commentlen:]
                    yield ent.objectname, raw
            return


def extract_lib(pbd_path):
    """单 PBD: 所有 .dwo 条目 -> {dwname: {columns, sql}}

    PDW0900 (PB9): GBK 串流 + 裸 SELECT; PDW1100 (PB10+/Unicode 库): UTF-16LE 串流
    + PBSELECT 语法。
    """
    out = {}
    for name, raw in iter_entries(pbd_path):
        if not name.lower().endswith(".dwo"):
            continue
        magic = raw[:7]
        if magic == b"PDW0900":
            items = scan_strings(raw)
            sql = extract_sql(raw)
        elif magic == b"PDW1100":
            items = scan_strings_utf16(raw)
            sql = extract_sql(raw)
        else:
            continue
        cols = parse_dwo_strings(items)
        out[name[:-4]] = {"columns": [c for c in cols.values() if c["dbname"] or c["values"]],
                          "sql": sql}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbd")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--root", help="--all 模式: 从此目录递归找 .pbd")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "docs"))
    args = ap.parse_args()

    targets = []
    if args.pbd:
        targets.append(args.pbd)
    elif args.all:
        root = args.root or "."
        for r, _d, fs in os.walk(root):
            for f in fs:
                if f.lower().endswith(".pbd"):
                    targets.append(os.path.join(r, f))
    for pbd in targets:
        lib = os.path.splitext(os.path.basename(pbd))[0]
        dws = extract_lib(pbd)
        if not dws:
            continue
        out_path = os.path.join(args.out_dir, f"dw_sem_{lib}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"lib": lib, "dw_count": len(dws), "dws": dws}, f, ensure_ascii=False)
        n_ct = sum(len(d["columns"]) and sum(1 for c in d["columns"] if c["values"]) for d in dws.values())
        print(f"{lib:24s} dws={len(dws):4d} coded={n_ct:4d} -> {os.path.basename(out_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
