# Matching playbook (old GCC, Thumb, -O2)

A checklist to work through in order, stopping at the first match. Steps 1 and 3 are
automatic (`auto.py` runs skeleton, fixups, scoring and `mutate.py` in one go). Written
for GCC 2.9x-era compilers (agbcc, camelot gcc-2.96) emitting Thumb code. The tells below
come from matching real functions with them, but check each one against your compiler.

## 0. Triage (seconds)
- Run `cluster.py` first. If the target has an already-matched sibling (`*` in the
  output), copy that C, rename it, and remap constants and callees. That is usually an
  instant match, and in practice it gave most of the speed-up.
- Skip (or plan a fakematch) when the function carries its own rodata (`.section`/
  `.incrom` in its .s), calls through `_call_via_*` with r8+ saved, or uses a pooled
  literal as a `sub` operand.
- Code linked to run from RAM (overlays) may need the RAM copies of libgcc helpers
  (e.g. an explicit `_divsi3` variant instead of `/`).

## 1. Skeleton (auto): `skel.py FUNC`
m2c output with `M2C_FIELD` rewritten to raw offsets, the signed `/ 2^k` idiom restored,
the return type taken from the epilogue tell, and unknown types mapped to `int`.

## 2. Tells to read off the asm before editing
| asm | C |
|---|---|
| `pop {r1}` + `bx r1` | non-void return (even if the value is unused) |
| `pop {r0}` + `bx r0` | void |
| `ldr rA,=global; ldr rB,=OFF; add` (add done at runtime) | index a typed array alias of the global (`extern short g_s16[] __asm__("g"); g_s16[OFF/2]`). `*(T*)(g+OFF)` folds into one literal |
| several offsets reached as `add r1,#1` from one base | a partial struct view with adjacent members, not raw `p[off]` |
| `ldrb r2,[r1]; mov r3,r2; cmp r3,#0` | decrement in place and re-read: `u[x]--; if (u[x] == 0)` |
| `lsl #24; lsr #24` after an add | u8 local or field |
| `ldrsh` | s16 field or `(short)` cast |
| extra `lsl #16; asr #16` on a parameter | declare the parameter `int`, not `short` |
| down-counter `sub rN,#1; cmp rN,#0; bge` plus a walking pointer | `for (i = 0; i < N; i++) a[i]` (gcc reverses it) or `for (i = N-1; i >= 0; i--)` |
| descending store loop with the base literal loaded late | index loop counting down `((T*)(b+LO))[i] = 0` rather than `*q-- = 0` |
| `mov rX, rY` and the loop uses both | split temp: `do { t = v + K; v = t; } while (t <= L)` |
| u16 constant via `ldrh rX,=K` at a large offset | gcc pools short constants for reg+reg stores. A small-offset struct field (or an `int v = K` local) gives `mov`, though the local can reorder code |
| DMA `stmia r3!,{r0,r1,r2}` where src/count are not reused | macro whose asm marks the operands `"+r"` |

## 3. Greedy playbook (auto): `mutate.py TU FUNC [start.c]`
P1 commutative operand order · P2 declaration order · P3 independent statement order ·
P4 signedness · P5 loop bound form (<, <=, !=) · P6 re-read instead of local ·
P7 local instead of re-read · P8 `v = E + 1` -> `v = E; v++` · P9 for <-> while ·
P10 index <-> pointer arithmetic · P11 name a subexpression in a local first.
It hill-climbs on the instruction-diff count, with a 2-step beam on plateaus. It narrows
gaps; it rarely finishes a match by itself.

## 4. Manual patterns (the most frequent wins)
1. A named local where the original loads early; a re-read where it reloads.
2. Expression and operand order exactly as the asm computes it (`(b - a) * s` vs `s * (b - a)`).
3. `param -= K;` in place to reuse the argument register.
4. Mask into a named local before OR-ing (`m = v & 0xe00; x = (x & 0xf1ff) | m`).
5. `for (i = 0; i != n; i++)` produces the guarded do-while list walk.
6. A counted for-loop with an early `break`; the length check first in compound conditions.
7. Field stores in the same order as the asm's stores.
8. Partial struct views (named, local to the file) whenever several offsets share a base.

## 5. Near-miss -> permuter: `permbatch.sh SECONDS TU:Func ...`
Most useful for diffs that are only register allocation. Needs a TU the permuter can
compile standalone.
