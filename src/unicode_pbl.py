#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unicode PBL/PBD 容器解析器 (pbl_util 的 unicode 分支不可用, 本模块为其替代)

字节布局 (nhbase.pbd 校准, 2026-10-02):
  HDR   = 1024B: 'HDR*' + UTF-16LE "PowerBuilder" + UTF-16LE 版本"0600"@32
  NOD   = 首个 'NOD*' (实测 @0x600); 头 24B: [NOD*][left4][parent4][right4]
          [spaceleft2@16][firstnamepos2@18][entry_count2@20][lastnamepos2@22]
          条目区从块内偏移 32 (0x20) 起
  ENT*  = 固定 28B 头 + 名字区:
          [ENT*4][version 8B UTF-16LE][first_dat_offset 4B][object_size 4B]
          [time 4B][commentlen 2B][namelen 2B][name UTF-16LE namelen B]
          (namelen 含 2B 结束符; 条目步长 = 28 + namelen)
  DAT   = 512B: [DAT*4][next_offset 4B][datalen 2B][data...]

用法:
  py -3 tools/unicode_pbl.py <pbd路径>            # 列条目清单
  from unicode_pbl import read_entries, entry_data # 供 parse_pdw0900/parse_srd 复用
"""
import os
import re
import struct
import sys


class Entry:
    __slots__ = ("name", "offset", "size", "time", "commentlen", "namelen")

    def __init__(self, name, offset, size, time, commentlen, namelen):
        self.name = name
        self.offset = offset
        self.size = size
        self.time = time
        self.commentlen = commentlen
        self.namelen = namelen

    def __repr__(self):
        return f"<{self.name} off={self.offset:#x} size={self.size}>"


def _first_nod(data):
    m = re.search(rb"NOD\*", data[:1 << 20])
    return m.start() if m else -1


def read_entries(path):
    """解析 Unicode PBL/PBD 的条目目录 -> [Entry]

    NOD 之间经 left(@4)/parent(@8)/right(@12) 三指针成图 (实测 yysfjk.pbd 第二 NOD
    经 left 回指首块, right=0) —— 沿三指针收集全部 NOD 再逐块解析。
    """
    with open(path, "rb") as f:
        data = f.read()
    nod = _first_nod(data)
    if nod < 0:
        raise ValueError(f"未找到 NOD*: {path}")
    # 收集全部 NOD
    nods = []
    seen_nods = set()
    queue = [nod]
    while queue:
        n = queue.pop()
        if n <= 0 or n >= len(data) or n in seen_nods or data[n:n + 4] != b"NOD*":
            continue
        seen_nods.add(n)
        nods.append(n)
        for ptr in (4, 8, 12):
            queue.append(struct.unpack("<I", data[n + ptr:n + ptr + 4])[0])
    entries = []
    for nod in nods:
        count = struct.unpack("<H", data[nod + 20:nod + 22])[0]
        pos = nod + 32  # 条目区
        for _ in range(count):
            if data[pos:pos + 4] != b"ENT*":
                break
            first_dat = struct.unpack("<I", data[pos + 12:pos + 16])[0]
            size = struct.unpack("<I", data[pos + 16:pos + 20])[0]
            tim = struct.unpack("<I", data[pos + 20:pos + 24])[0]
            commentlen = struct.unpack("<H", data[pos + 24:pos + 26])[0]
            namelen = struct.unpack("<H", data[pos + 26:pos + 28])[0]
            raw = data[pos + 28:pos + 28 + namelen]
            name = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
            entries.append(Entry(name, first_dat, size, tim, commentlen, namelen))
            pos += 28 + namelen
    return entries


def entry_data(path, ent):
    """沿 DAT 链取条目原始字节"""
    with open(path, "rb") as f:
        data = f.read()
    out = bytearray()
    off = ent.offset
    seen = set()
    while off > 0 and off < len(data) and off not in seen:
        seen.add(off)
        if data[off:off + 4] != b"DAT*":
            break
        nxt = struct.unpack("<I", data[off + 4:off + 8])[0]
        datalen = struct.unpack("<H", data[off + 8:off + 10])[0]
        out += data[off + 10:off + 10 + datalen]
        off = nxt
    return bytes(out)


def entry_text(path, ent, encoding="utf-16-le"):
    """条目文本 (源码对象): 去掉注释长度前缀后按给定编码解码"""
    raw = entry_data(path, ent)
    if ent.commentlen:
        # 注释前缀在 UTF-16 源里按 2 字节/字符计
        raw = raw[ent.commentlen * 2:]
    return raw.decode(encoding, errors="replace")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    entries = read_entries(path)
    print(f"{os.path.basename(path)}: {len(entries)} 条目")
    for e in entries:
        print(f"  {e.name:40s} off={e.offset:#8x} size={e.size:7d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
