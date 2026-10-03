# Format notes: Unicode-built PBL/PBD container (PB10+/PB11)

Byte-calibrated against real deployed libraries (a 38-object and a 48-object
library, cross-checked against per-object exports from an independent tool).

## Header

The library header block is **1024 bytes** (not 512 as in ANSI-era PBLs):

| Offset | Size | Content |
|--------|------|---------|
| 0x00 | 4 | `HDR*` |
| 0x04 | 24 | `PowerBuilder` as UTF-16LE (magic: bytes `4..6 == 50 00` ⇒ Unicode) |
| 0x20 | 8 | version string, UTF-16LE (`"0600"`) |
| 0x28 | 4 | creation timestamp (unix time, LE) |
| ... | | library comment (UTF-16LE) |

## Node blocks (NOD)

- First `NOD*` found by scan (in practice at offset 0x600: 1024-byte header +
  a 512-byte free-space bitmap block).
- Node block header (little-endian):

| Offset | Size | Content |
|--------|------|---------|
| 0x00 | 4 | `NOD*` |
| 0x04 | 4 | left sibling |
| 0x08 | 4 | parent |
| 0x0C | 4 | right sibling |
| 0x10 | 2 | space left |
| 0x12 | 2 | position of first object name |
| 0x14 | 2 | **entry count** |
| 0x16 | 2 | position of last object name |

- **Entries start at block offset 0x20** (32).
- **NOD blocks form a directed graph, not a linear chain.** Real libraries
  exist where the second node's *left* pointer refers back to the first node
  while every node's *right* is zero — walking only `right` misses all
  entries in the second node. Walk `left`, `parent`, `right` from the first
  node with a visited set.

## Entry records (ENT*)

Fixed 28-byte head + variable name area:

| Offset | Size | Content |
|--------|------|---------|
| 0x00 | 4 | `ENT*` |
| 0x04 | 8 | version, UTF-16LE |
| 0x0C | 4 | file offset of first data block |
| 0x10 | 4 | object net size (bytes) |
| 0x14 | 4 | timestamp |
| 0x18 | 2 | comment length |
| 0x1A | 2 | name length **in bytes, including the 2-byte NUL terminator** |
| 0x1C | namelen | object name, UTF-16LE (e.g. `gf_nh_readzysfxx.fun`) |

Stride: `28 + namelen` bytes to the next record.

## Data blocks (DAT)

Same as ANSI era: 512-byte blocks, `[DAT*][next-offset u32][data-len u16][payload]`,
chain until `next == 0`. For source objects the payload begins with a comment
prefix (`commentlen` *characters*, 2 bytes each in Unicode libraries) before the
text. Compiled entries (`*.dwo` DataWindows etc.) start directly with their own
magic (`PDW1100` for PB10/11 builds).

## Caveat

PB9-era (ANSI) libraries use 512-byte headers, 4-byte version fields, ASCII
names (`24 + namelen` stride), and a different first-NOD offset (1024).
A robust reader should detect the encoding from the header magic and branch.
