# pb9-forensics

A generic toolkit for reverse-engineering **PowerBuilder 9/11 compiled artifacts**:
PBL/PBD containers, compiled DataWindows, PB machine-code DLLs. All format
knowledge below was byte-calibrated against compiled PowerBuilder libraries.

Tools and reverse-engineered format knowledge for PowerBuilder 9/11 compiled artifacts.

## What's here

| Path | What |
|------|------|
| `src/unicode_pbl.py` | Container parser for **Unicode-built PBL/PBD** (PB10+/PB11, 1024-byte header, UTF-16LE names). Public implementations of this layout are rare; this one was byte-calibrated against real libraries. |
| `src/parse_pdw0900.py` | Direct parser for **compiled DataWindows** inside PBDs: both `PDW0900` (PB9, GBK string streams, raw SELECT) and `PDW1100` (PB10+, UTF-16LE streams, `PBSELECT(...)` syntax). Extracts per-column `dbname`, **code tables** (display/data value pairs), and SQL — no PB IDE required. |
| `src/pbd_decompile2.ps1` | Driver that reflects into the PbdViewer decompiler DLL and dumps every object of a PBD/PBL/**PB machine-code DLL** to annotated pseudo-source. |
| `src/scan_exe_pe.py` | PE fingerprint scanner: bits/linker/imports/exports/Rich-header/compiler heuristics (MSVC/Delphi/VB/PowerBuilder/Qt...). |
| `src/dll_census.py` | Walk a deployment tree, MD5-dedupe every DLL/OCX, fingerprint each, score business-semantic density (SQL statements, PB object names, CJK strings), and tier the results. |
| `src/census_if_forms.py` | Measure decompiler rendering quality against a ground-truth corpus (control-flow keyword census, per-function pairing). |
| `patches/` | Diffs against the original [PbdViewer](https://bbs.kanxue.com/thread-247372.htm) C# source (original by Hucxy). See `ATTRIBUTION.md`. |
| `format-notes/` | Byte-calibrated format specs: Unicode PBL container, PDW0900/PDW1100 DataWindow format, and decompiler gotchas. |

## Highlights (format facts these tools rely on)

1. **NOD blocks form a graph, not a chain** — sibling/parent pointers (`left@+4, parent@+8, right@+12`) vary; single-direction walks miss entries or crash on seek-to-garbage. Walk all three pointers with a visited set. Found in both Unicode PBLs and PB machine-code DLLs.
2. **Code tables (dropdown value lists) live in compiled DataWindows as plaintext**, format `display<TAB>data`, rows joined by `/`, stored length-prefixed: `[u32 byte-length incl. terminator][text][NUL]` (PB9: GBK, single NUL; PB11: UTF-16LE, double NUL).
3. **Function-name recovery**: the p-code function table's `Index` is a **position into the object's own `FunctionDefinitions` table** — not the GlobalIndex-addressed all-functions table (joining those two is what produces `func_NNN` artifacts).
4. **Event `RETURN` protocol**: every event return compiles to a 4-line `if isvalid(message) then goto / return / goto / return message.returnvalue` block; folding it (distinguishing function-tail epilogue from mid-function returns) removes ~75% of decompiled `goto` noise.
5. `do while true` retry loops have no conditional test in p-code; recognize them by pairing a backward jump (the back-edge) with an in-loop forward jump landing right after it (`exit`), yielding `do/loop/exit/continue` structure.

## Usage

```bash
# list objects in a Unicode-built PBD
python src/unicode_pbl.py <file.pbd>

# extract DataWindow semantics (columns/dbname/code tables/SQL) from a deployed PBD
python src/parse_pdw0900.py --pbd <file.pbd>            # single library
python src/parse_pdw0900.py --all --root <deploy-root>  # walk a tree

# fingerprint a whole deployment
python src/dll_census.py --root <deploy-root>

# decompile a PBD / PB machine-code DLL to pseudo-source (needs PbdViewerCore.dll, see ATTRIBUTION)
powershell -File src/pbd_decompile2.ps1 -InputFile <file.pbd|file.dll> -OutDir <out>
```

## License

- `src/*` original tools and `format-notes/*`: MIT (see `LICENSE`)
- `patches/*` and anything referencing PbdViewer internals: the upstream is (c) Hucxy (看雪论坛); apply patches to your own copy of the upstream source. Their licensing terms apply to the upstream files.
