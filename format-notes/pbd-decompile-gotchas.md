# Format notes: p-code decompiler gotchas

Field notes from decompiling ~430 libraries / ~35,000 objects of PB9 code with
PbdViewer, fixing three systematic artifact classes. Each fix is measured
against a ground-truth corpus (per-object exports from an independent
decompiler as reference, then whole-corpus keyword censuses).

## 1. Function names: three numbering spaces

Inside a compiled object there are three index spaces that are easy to conflate:

1. `PbFunction.Index` — an entry of the **p-code function table** (4-byte
   records; a ushort field points into…)
2. the object's **own definition table** `FunctionDefinitions` (48-byte
   records: local index, name, params, return type)
3. `AllFunctionDefinitions` — the inheritance-merged table **addressed by
   GlobalIndex** (ushort at offset 20 of each definition record), which
   includes inherited system definitions (`create`, `destroy`, `classname`,
   `postevent`, `triggerevent` …) at the low slots.

**The p-code function table's Index addresses the object's own
`FunctionDefinitions` positionally.** Joining `Index` against the merged
table (either by local order or by GlobalIndex) produces the classic
`func_NNN` / system-name-takeover artifacts: in one real corpus,
12,652 `func_NNN` and 10,357 system-name takeovers, dropping to 0 after the
correct join. Also beware: when building an index→definition map, a test
like `if (d.Index)` skips index 0.

## 2. Event `RETURN` message protocol

Every `RETURN` in an *event* compiles to a four-line protocol:

```
if isvalid(message) then goto <EPILOGUE>
    return 0
    goto <EPILOGUE+...>
    return message.returnvalue
```

Rendered verbatim this is ~2 extra `goto`s per return site (in one corpus:
804 total decompiled `goto`s vs 145 in ground truth). Folding rules:

- Pattern-match `isvalid(message)` — **PB9 renders it without the `::`
  prefix**; older-written patterns expecting `::message` never match.
- If nothing follows the 4-line block: function-tail epilogue, fold silently.
- If code follows (mid-function explicit `return`): keep a visible `return`
  line — dropping it loses control-flow semantics.

## 3. `do while true` retry loops

A constant-true condition compiles to **no conditional test at all**, so
test-based loop recognition misses the loop entirely and its body renders
flat with raw `goto`s. Recognition rule: pair a **backward jump** (the
back-edge) with an **in-loop forward jump landing immediately after the
back-edge line** (`exit`); mark the back-edge line `loop`, the loop head
`do while true`, in-loop jumps landing on the back-edge's successor `exit`,
and remaining backward jumps to the head `continue`.

## 4. Compound conditions

The compiler splits `A and B` into consecutive same-target `JmpIfFalse`s
(mergeable into `if (A) and (B) then`, iterate to fixpoint for 3+ terms);
`A or B` uses a `JmpIfTrue`+`JmpIfFalse` pair with different targets
(the true-target equals the first body line). PB's single-line form
`if cond then stmt` (body = exactly one simple statement) should be folded
back to one line — multi-line expansion was the single biggest remaining
readability artifact in `destroy`-type cleanup events (~25 expandable ifs per
window).

## 5. Measuring rendering quality honestly

When comparing decompiled output against ground truth:

- **Watch for truncated reference corpora.** One widely-used decompiler's
  demo build truncates long function bodies mid-file; comparing against it
  inflated the apparent `if` count by +67% in our first census. Filter
  truncated bodies out.
- Count `if` at statement starts, not `\bif\b` (else `end if` lines count).
- Pair per function name, with `create/destroy ↔ constructor/destructor`
  aliasing; unpaired functions in truth = implicit ones (no user source).
