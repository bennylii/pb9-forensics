#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DLL 全量普查: 去重 + 编译器指纹 + PB 机码识别 + 业务语义密度 + 三档分类

只读扫描指定根目录，产出:
  docs/dll_census.json   全量普查记录 + 三档分类
用法: py -3 tools/dll_census.py [--root <部署根目录>]
"""
import os
import re
import sys
import json
import hashlib
import argparse

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import scan_exe_pe as PE  # noqa: E402

# 运行库/第三方黑名单 (系统运行库档)
RUNTIME_PAT = re.compile(
    r"^(pb(vm|dwe|jag|mss|shr|pbo|jvm|soap)\d*|libj(cc|log|utilsybheap)|pbrtc|pbsys|pbacc|"
    r"qt5|qt4|qwindows|qminimal|qico|qgif|qjpeg|qsvg|qt-mt|"
    r"oci|orasql|ntwdblib|dbnetlib|dbmssocn|libmysql|"
    r"libcurl|zlib1|ssleay|libeay|libssl|xerces|expat|sqlite3|"
    r"icu|xtp|duilib|gdiplus|opengl32sw|d3d|msimg32)\.?", re.I)

# 设备/通用组件关键词 (通用组件档)
DEVICE_PAT = re.compile(
    r"(iccard|mwic|dcic|termb|vcic|readcard|reader|camera|printer|serialport|ledno|"
    r"barcode|qrcode|jmail|graph|scan|desalgo|encrypt|getserial|getcpuid|getnet|"
    r"shellrunas|jtts|voice| speech|jpgdll|espcap|high|cam)\w*", re.I)

# 业务语义词 (GBK 中文业务词)
BIZ_WORDS = ["病人", "医嘱", "收费", "结算", "手术", "门诊", "住院", "病区", "药", "诊断",
             "病历", "挂号", "护士", "医生", "检验", "检查", "医保", "费用", "申请", "报告",
             "库存", "物资", "病案", "体检", "预约", "皮肤", "随访"]
RE_SQL = re.compile(r"\b(FROM|INSERT INTO|UPDATE|DELETE FROM)\s+[A-Za-z_]\w{2,}", re.I)
RE_PBOBJ = re.compile(r"\b[dsuwv]_[a-z][a-z0-9_]{3,}\.(dwo|win|udo|fun|men)\b", re.I)
RE_IDENT = re.compile(r"\b(?:gf|wf|of|uf)_[a-z][a-z0-9_]{3,}\b", re.I)


def gbk_strings(data, min_len=4, limit=4000):
    """提取 GBK 中文串 (业务语义密度用): 扫 GBK 双字节游程"""
    out = []
    i = 0
    n = len(data)
    while i < n - 1 and len(out) < 300:
        start = i
        while i < n - 1:
            b = data[i]
            if 0x81 <= b <= 0xFE and 0x40 <= data[i + 1] <= 0xFE and data[i + 1] != 0x7F:
                i += 2
            else:
                break
        if i - start >= min_len * 2:
            try:
                s = data[start:i].decode("gbk")
                out.append(s)
            except Exception:
                pass
        i += 1
    return out


def classify(name, info, biz_score):
    base = os.path.basename(name)
    if info.get("pb_machine"):
        # PB 机码 DLL = 编译业务库 (emr_component/cp_bzzk/webcallpb)
        return "business"
    if RUNTIME_PAT.search(base):
        return "runtime"
    if any("pbvm" in d or "pbdwe" in d for d in info.get("dlls", [])):
        # 导入 PB VM 但名字非 PB 运行库 => PB 机码业务 DLL
        return "business"
    if biz_score >= 3 or info.get("pb_machine") or RE_SQL.search(_text_cache.get(name, "")):
        return "business"
    if DEVICE_PAT.search(base):
        return "device"
    return "generic" if biz_score == 0 and len(info.get("exports", [])) < 50 else "business"


_text_cache = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    args = ap.parse_args()

    seen_md5 = {}
    records = []
    n_files = 0
    for r, _d, fs in os.walk(args.root):
        for fn in sorted(fs):
            if not fn.lower().endswith((".dll", ".ocx")):
                continue
            p = os.path.join(r, fn)
            n_files += 1
            try:
                data = open(p, "rb").read()
            except OSError:
                continue
            md5 = hashlib.md5(data).hexdigest()
            if md5 in seen_md5:
                continue
            seen_md5[md5] = p
            info = PE.scan(p)
            rel = os.path.relpath(p, args.root)
            # PB 机码识别: 节区 AUTO/DGROUP 或 __fn_* 导出
            pb_machine = False
            if "sections" in info:
                pass
            exports = info.get("exports", [])
            if any(re.match(r"^__fn_\d+", x) for x in exports[:20]):
                pb_machine = True
            # 业务语义密度
            _text_cache[p] = data[:min(len(data), 6 * 1024 * 1024)].decode("latin-1", errors="replace")
            text = _text_cache[p]
            biz_hits = sum(text.count(w) for w in BIZ_WORDS)
            sqls = len(RE_SQL.findall(text))
            pbobjs = len(RE_PBOBJ.findall(text))
            idents = len(RE_IDENT.findall(text))
            biz_score = (1 if biz_hits >= 5 else 0) + (1 if sqls >= 2 else 0) + \
                        (1 if pbobjs >= 2 else 0) + (1 if idents >= 3 else 0)
            info.update({"rel": rel, "md5": md5, "pb_machine": pb_machine,
                         "biz_hits": biz_hits, "sqls": sqls, "pbobjs": pbobjs,
                         "idents": idents, "biz_score": biz_score,
                         "tier": classify(p, info, biz_score)})
            records.append(info)

    tiers = Counter = {}
    for r in records:
        tiers.setdefault(r["tier"], []).append(r["rel"])
    out = {"scanned_files": n_files, "unique": len(records),
           "tiers": {k: len(v) for k, v in sorted(tiers.items())},
           "records": [{k: v for k, v in r.items() if k != "_"} for r in records]}
    # 截断 record 里的超长字段
    for r in out["records"]:
        r["exports_n"] = len(r.pop("exports", []))
        r.pop("dlls", None)
        r.pop("rich", None)
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "dll_census.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"扫描 {n_files} 个 DLL 文件, 去重后 {len(records)} 个唯一")
    for k, v in sorted(out["tiers"].items()):
        print(f"  [{k}] {v}")
    print("\n业务核心 TOP20 (按 biz_score):")
    for r in sorted((r for r in records if r["tier"] == "business"),
                    key=lambda x: -x["biz_score"])[:20]:
        print(f"  {r['rel'][:60]:60s} pb机码={r['pb_machine']} biz={r['biz_score']} "
              f"sql={r['sqls']} obj={r['pbobjs']} 中文={r['biz_hits']}")
    print(f"\nOK -> docs/dll_census.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
