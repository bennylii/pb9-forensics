# Attribution

## PbdViewer (upstream)

The decompiler driver and patches in this repository are built on top of
**PbdViewer**, a C# PowerBuilder p-code decompiler originally published by
**Hucxy** on the Kanxue (看雪) forum:

- Thread: https://bbs.kanxue.com/thread-247372.htm

This repository does **not** redistribute the upstream source. It publishes:

1. `patches/*.patch` — diffs to apply to your own copy of the upstream source
2. `src/pbd_decompile2.ps1` — a driver script that reflects into the built
   `PbdViewerCore.dll`

If you use the patches, keep the upstream author's copyright notice in the
upstream files and observe whatever licensing terms the original author
published with the tool.

## What the patches change

- `001-pcodehelper-*.patch` — decompiler rendering quality: event-`RETURN`
  message-protocol folding (PB9 renders `isvalid(message)` without the `::`
  prefix the pattern expected), real implementation of `ParseGoto`
  (`do while true` loop pairing, backward-jump → `continue`, forward
  `JmpIfTrue` → `if cond then exit`), `ParseIfMerge` (same-target adjacent
  `JmpIfFalse` chains → `and` conditions), `ParseSingleLineIf` (PB single-line
  `if cond then stmt` form), `elseif` spelling rebuild.
- `002-pbfile-*.patch` — `GetNodeList`: NOD blocks are linked through
  left(@4)/parent(@8)/right(@12) as a graph, not a one-direction chain;
  single-direction walks miss entries or throw on seek-to-garbage. Now walks
  all three pointers with a visited set.
- `003-pbproject-*.patch` — per-entry parse isolation in the `PbProject`
  constructor: one malformed entry no longer aborts the whole library.
