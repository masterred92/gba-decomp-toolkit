# Signatures: finding the same function in two ROMs

```sh
python3 -m gbadt signatures build  <named_project> -o lib.sigs        # fingerprint every function
python3 -m gbadt signatures match  lib.sigs <target_project> -o hits.syms
python3 -m gbadt import-symbols    <target_project> hits.syms         # apply the names
python3 -m gbadt signatures show   <project> <function>               # see what gets masked
```

## The idea (tutor's note)
Two games from one studio, or two versions of one game, share lots of code: the sound driver,
memory copy and decompression helpers, often big parts of the engine. If a sibling game already
has a finished decomp, those shared functions already have names and matching C. We just need
to find them in *our* ROM.

We can't compare raw bytes, because a function's bytes change when it **moves**, even if the C
is identical. Three things store addresses or distances:

| What | Why it changes | What we do |
|---|---|---|
| `BL` call (Thumb, 4 bytes) | stores the *distance* to the callee | keep "this is a BL", blank the distance |
| literal-pool word holding `0x02…`/`0x03…`/`0x08…`/`0x09…` | absolute address of a RAM variable, ROM data or a function | blank the word |
| `B` that jumps *out* of the function (tail call), ARM `B`/`BL` | distance again | blank the offset |
| alignment padding at the end (`0000` or `46c0` nop) | depends on where the next function starts | trim it |

Everything else stays: the instructions, registers, small constants and hardware addresses like
`0x04000000` (those are the same in every GBA game). Then we hash it. Same hash on both sides,
and unique on both sides = very probably the same function.

Real example from our test (`signatures show`), the demo's `main` in two layouts:
```
layout A  08000168: 80 23 03 4a db 04 10 b5 1a 60 .. .. .. .. fe e7 03 04 00 00
layout B  0800017C: 80 23 03 4a db 04 10 b5 1a 60 .. .. .. .. fe e7 03 04 00 00
```
The raw bytes at `..` differ (the `BL fill_gradient` distance), the signatures are equal.

## Getting a named project from a finished sibling decomp
`build` reads names from a gbadt project. For a sibling game that already has a decomp:
1. Build the sibling decomp from **your own** ROM so you have its `.elf` (or use its `.map`/`.sym`).
2. `gbadt init sibling.gba projects/sibling` then
   `arm-none-eabi-nm sibling.elf > sibling.syms` and `gbadt import-symbols projects/sibling sibling.syms`.
3. `gbadt signatures build projects/sibling -o sibling.sigs`. The `.sigs` file only holds hashes,
   sizes, addresses and names, no game bytes.

## Reading the match report
`matched` names transferred, `ambiguous` the hash appears more than once on a side (common for tiny
helpers; resolve by hand), `too small` under `--min-size` (default 8 bytes), `no match` not found in
the target, `unnamed` skipped because the source name is just `sub_…` (use `--include-unnamed`).

## Limits
* A function only matches if it compiled **byte-identically** apart from addresses. Same source
  with a different compiler, different flags (e.g. Golden Sun vs The Lost Age), or a changed
  struct layout gives a different hash. A future "fuzzy" mode could score similarity instead.
* It depends on function boundaries from discovery. If a function is split or merged, its hash
  won't match.
* Compilers that **share literal pools between functions** (ARM ADS, e.g. the Webfoot DBZ games)
  put pool words outside the function that reads them; those words aren't masked, so expect fewer hits.
* Only 4-byte literal-pool words are masked. Pointers built in other ways (e.g. `ADR`, or constants
  computed with shifts) stay in the hash.
