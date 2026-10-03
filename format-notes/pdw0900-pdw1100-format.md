# Format notes: compiled DataWindows (PDW0900 / PDW1100)

Compiled DataWindows live inside PBL/PBD containers as `*.dwo` entries whose
payload starts with a version magic: `PDW0900` (PB9) or `PDW1100` (PB10/11).
Both store metadata as a stream of length-prefixed strings; they differ in
string encoding and SQL dialect.

## PDW0900 (PB9)

- Strings: `[u32 byte-length, including 1-byte NUL terminator][text, GBK][NUL]`
- Permissible bytes inside text: TAB/CR/LF, ASCII printable, GBK lead+trail.
- SQL dialect: raw `SELECT ... FROM ... WHERE ...` text (often with embedded
  comments).

## PDW1100 (PB10/11 — Unicode builds)

- Strings: `[u32 byte-length, including 2-byte NUL terminator][text, UTF-16LE][NUL NUL]`
- SQL dialect: `PBSELECT( VERSION(400) TABLE(NAME="t") COLUMN(NAME="t.c") ... )`
  pseudo-syntax rather than raw SQL.

## Region layout (both)

1. Front region: paint-time object records — control names (`t_3`, `ypmc_t`,
   `cb_ok`, ...), positions/sizes, fonts, colors, literal text (often stored
   **twice** — two records sharing one pool entry).
2. Retrieve-argument names (`:al_zyh` and bare forms).
3. Table region, repeating per column:
   `[column short name][qualified dbname "table.column"]` — in compiled PB9
   artifacts the dbname is frequently **upper-cased** relative to the source
   (`zy_bqyz.mzcs` → `ZY_BQYZ.MZCS`); compare case-insensitively.
   Bare (non-dotted) dbnames exist for computed/derived columns and appear as
   an adjacent **pair of identical identifiers**.
4. Trailing metadata copies of the column records, each optionally followed by
   the column's **code table**.

## Code tables (dropdown value lists)

Stored as plaintext with the source-level syntax:

```
display<TAB>data/display<TAB>data/.../
```

- Row separator `/`; within a row, **display first, data after the TAB**;
  either side may be empty (empty display row for `null`).
- data values may be numeric, alphabetic codes (`Z`, `+`, `-`, `Y`, `N`) or
  CJK words (`治愈/好转/未愈`) — do not assume numeric.
- Validation expressions (e.g. `1<TAB>if(sfjg=2,1,0)`) use the same
  display[TAB]syntax shape; discriminate by checking whether the data part
  contains `(` or `=`.
- Multiple columns may **share one code-table record** (stored once);
  attribution therefore needs the adjacent-column-record pairing, not just
  "nearest string".

## Extracted semantics worth automating

- per column: `dbname` (authoritative table.column), type string, initial
  value, code table pairs, validation, display format (on paint controls).
- SQL: table names via `FROM` (PB9) or `TABLE(NAME=)` (PB11) — cross-checking
  object SQL against a corpus of DataWindows yields the de-facto data
  dictionary of the application.
