#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 PE 可执行文件的框架指纹：位数/子系统/链接器版本/导入表/特征字符串

用法: py -3 tools/scan_exe_pe.py <目录...>
输出: 每个 exe 一行摘要 + 导入表关键 DLL
"""
import os, sys, struct, re

KEY_DLLS = ['mscoree', 'msvbvm60', 'pbvm', 'pbjvm', 'mfc', 'msvcr', 'msvcp',
            'vcruntime', 'ucrtbase', 'qt', 'libgcc', 'libstdc', 'bcb', 'cc32',
            'delphi', 'orant', 'oci', 'odbc32', 'sqlite', 'pbdwe', 'libcurl',
            'ws2_32', 'winhttp', 'wininet', 'user32', 'gdi32', 'advapi32',
            'oleaut32', 'ole32', 'shell32', 'comdlg32', 'version', 'crtdll']


def read_exports(data, sections, dd_rva):
    """读取导出表函数名列表（无导出返回 []）"""
    names = []
    if dd_rva == 0:
        return names
    def rva2off(rva):
        for rsz, roff, va, vsz in sections:
            if va <= rva < va + max(vsz, rsz):
                return rva - va + roff
        return None
    eo = rva2off(dd_rva)
    if eo is None or eo + 40 > len(data):
        return names
    nfuncs, nnames, addr_rva, name_rva, ord_rva = struct.unpack_from('<IIIII', data, eo + 20)
    np_base = rva2off(name_rva)
    if np_base is None:
        return names
    for i in range(nnames):
        np = rva2off(struct.unpack_from('<I', data, np_base + i * 4)[0])
        if np:
            e = data.find(b'\x00', np)
            if e > np:
                names.append(data[np:e].decode('gbk', errors='replace'))
    return names


def read_imports(data, sections, dd_rva):
    """读取导入表 DLL 名列表"""
    dlls = []
    if dd_rva == 0:
        return dlls
    def rva2off(rva):
        for rsz, roff, va, vsz in sections:
            if va <= rva < va + max(vsz, rsz):
                return rva - va + roff
        return None
    p = rva2off(dd_rva)
    if p is None:
        return dlls
    while p + 20 <= len(data):
        oft, ts, fc, name_rva, ft = struct.unpack_from('<IIIII', data, p)
        if name_rva == 0:
            break
        np = rva2off(name_rva)
        if np is not None:
            end = data.find(b'\x00', np)
            if end > 0:
                dlls.append(data[np:end].decode('gbk', errors='replace').lower())
        p += 20
    return dlls


def rich_header(data):
    """解析 Rich header，返回 [(prodid, build)]"""
    rich = b'Rich'
    idx = data.find(rich)
    if idx < 0:
        return []
    xor_key = struct.unpack_from('<I', data, idx + 4)[0]
    # 向前找 DanS 签名
    start = data.rfind(b'DanS', 0, idx)
    if start < 0:
        return []
    start += 4
    entries = []
    p = start
    while p + 8 <= idx:
        a, b = struct.unpack_from('<II', data, p)
        if a == 0xFFFFFFFF:
            break
        prod = a ^ xor_key
        build = b ^ xor_key
        entries.append((prod, build))
        p += 8
    return entries


def check_feature(data, pattern, radius=1):
    return pattern in data

def scan(path):
    with open(path, 'rb') as f:
        data = f.read(3 * 1024 * 1024)  # 前 3MB 足够
    info = {'path': path, 'size': os.path.getsize(path)}
    if len(data) < 0x40 or data[:2] != b'MZ':
        info['error'] = 'not PE'
        return info
    pe_off = struct.unpack_from('<I', data, 0x3C)[0]
    if pe_off + 24 > len(data) or data[pe_off:pe_off+4] != b'PE\x00\x00':
        info['error'] = 'no PE sig'
        return info
    fh = pe_off + 4
    machine, nsects, _, _, _, opt_size, chars = struct.unpack_from('<HHIIIHH', data, fh)
    oh = fh + 20
    magic = struct.unpack_from('<H', data, oh)[0]
    info['bits'] = 64 if magic == 0x20B else 32
    info['machine'] = 'x64' if machine == 0x8664 else ('x86' if machine == 0x14C else hex(machine))
    info['linker'] = '%d.%02d' % struct.unpack_from('<BB', data, oh + 2)
    info['subsystem'] = struct.unpack_from('<H', data, oh + 68)[0]
    # 数据目录
    if magic == 0x10B:
        dd_base = oh + 96
    else:
        dd_base = oh + 112
    # 导入表 RVA = DataDirectory[1]
    import_rva, import_size = struct.unpack_from('<II', data, dd_base + 8)
    export_rva, export_size = struct.unpack_from('<II', data, dd_base)
    # sections
    sections = []
    sec = oh + opt_size
    for i in range(nsects):
        name = data[sec+i*40:sec+i*40+8].rstrip(b'\x00').decode('latin1', 'replace')
        vsize, vaddr, raw_size, raw_off = struct.unpack_from('<IIII', data, sec + i*40 + 8)
        sections.append((raw_size, raw_off, vaddr, vsize))
    dlls = read_imports(data, sections, import_rva)
    info['dlls'] = dlls
    info['exports'] = read_exports(data, sections, export_rva)
    # 特征
    feats = []
    low = data.lower()
    if b'mscoree' in low: feats.append('.NET')
    if b'msvbvm60' in low: feats.append('VB6')
    if b'pbvm90' in low or b'pbvm100' in low: feats.append('PowerBuilder')
    if b'pbdwe90' in low or b'pbdwe' in low: feats.append('PB-DataWindow')
    if re.search(rb'mfc\d\d', low): feats.append('MFC')
    if re.search(rb'msvcr\d+\.dll', low) or re.search(rb'msvcp\d+\.dll', low) or b'vcruntime' in low: feats.append('MSVC-RT')
    if b'ucrtbase' in low: feats.append('UCRT')
    if b'borland' in low or b'embarcadero' in low or b'turbo delphi' in low or b'codegear' in low: feats.append('Delphi')
    if re.search(rb'\x00TForm\x00|\x00TApplication\x00|\x00TButton\x00', data): feats.append('VCL-classes')
    if b'libcurl' in low: feats.append('libcurl')
    if b'qt5' in low or b'qt4' in low: feats.append('Qt')
    if b'orant' in low or b'oci.dll' in low: feats.append('Oracle')
    rich = rich_header(data)
    if rich:
        prodids = set(p >> 16 for p, b in rich)
        # 0x10x? MSVC 编译器族: 0x01=MSVC compiler, 0x02=MASM, 0x06=link, 0x07=cvtres, 0x08=alink
        fam = []
        for pid in prodids:
            fam.append('0x%02X' % pid)
        info['rich'] = ','.join(sorted(fam))
    else:
        info['rich'] = None
    info['feats'] = feats
    return info


def main():
    targets = sys.argv[1:]
    show_exports = False
    if '-e' in targets:
        show_exports = True
        targets.remove('-e')
    if not targets:
        targets = ['.']
    rows = []
    for t in targets:
        if os.path.isfile(t):
            rows.append(scan(t))
            continue
        for root, dirs, files in os.walk(t):
            for fn in files:
                if fn.lower().endswith(('.exe', '.dll', '.ocx')):
                    p = os.path.join(root, fn)
                    rows.append(scan(p))
    subsys = {1: 'NATIVE', 2: 'GUI', 3: 'CUI', 9: 'WINDOWS'}
    for r in sorted(rows, key=lambda r: r['path']):
        rel = r['path'].replace('\\', '/')
        if 'error' in r:
            print('[%s] %s' % (r['error'], rel))
            continue
        ss = subsys.get(r['subsystem'], r['subsystem'])
        feats = r['feats']
        rich = ' rich:' + r['rich'] if r['rich'] else ''
        print('[%sbit/%s linker%s] %-38s %s' % (
            r['bits'], ss, r['linker'], rel.split('/')[-1], ','.join(feats) + rich))
        kd = [d for d in r['dlls'] if any(k in d for k in KEY_DLLS)]
        if kd:
            print('    imports: %s' % ', '.join(sorted(set(kd))))
        if show_exports and r['exports']:
            print('    exports(%d): %s' % (len(r['exports']), ', '.join(r['exports'][:80])))


if __name__ == '__main__':
    main()
