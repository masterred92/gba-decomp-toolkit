# gba-decomp-toolkit

A general-purpose scaffold generator for **matching decompilation** of Game Boy Advance
software. Point it at a ROM *you* own and it builds a project that reassembles to a
byte-identical ROM, which you then replace function by function with C.

It is not tied to any game, contains no game code or assets, and is tested only on a tiny
MIT-licensed homebrew ROM built from source in `tests/homebrew/`.

## Bring your own ROM
* You supply `baserom.gba` from your own cartridge. It is copied into your local project only.
* `.gitignore` blocks `*.gba`, `*.bin`, `baserom*` and generated `projects/`.
* Share **only** your own work: configs, symbol names, matched C, notes, tools. Never ROMs,
  extracted assets, or the generated `asm/` that encodes the original bytes.

## Pipeline
| Step | Command / file | Notes |
|---|---|---|
| Identify | `python3 -m gbadt info rom.gba --expect-sha1 <sha1>` | header title/code/maker, 0x96 byte, complement check, entry branch, SHA1 |
| Discover | `gbadt/discover.py` | strong clues (entry, Thumb `BL` targets, `addr|1` pointers in literal pools), weak clues (`PUSH {..,LR}`, ARM `STMFD`), then a *sweep* that finds each function's end (return + literal pool + padding) so small leaf functions after it are found and scheduled prologues don't split a function. Each segment records `found_by`. Still a heuristic |
| Split + scaffold | `python3 -m gbadt init rom.gba projects/mygame` | one `.s` per function (raw `.2byte`/`.4byte` + objdump comments), data as `.incbin`, `config.json`, linker script, Makefile |
| Rebuild + verify | `make -C projects/mygame` | `arm-none-eabi-as/ld/objcopy`, then `sha1sum -c` |
| Find known functions | `python3 -m gbadt signatures build/match` | fingerprints with addresses masked, finds a named sibling's functions in your ROM, output feeds `import-symbols` ([docs/signatures.md](docs/signatures.md)) |
| Match | `python3 -m gbadt match <proj> sub_08001234 guess.c --cc <compiler> --cflags ...` | compiles your C, compares bytes with the original function |

Splitting is deliberately simple and always byte-identical. For symbolic, label-based
disassembly you can swap in [luvdis](https://github.com/aarant/luvdis) (a GBA-specific Thumb
disassembler); splat targets MIPS/PPC-era consoles and is not used here.

## Compilers
* Toolchain: `scripts/install_toolchain.sh` installs the ARM GNU toolchain in user space.
* Most first-party/Japanese GBA titles were built with an old GCC; pret's
  [agbcc](https://github.com/pret/agbcc) recreates it. `scripts/install_agbcc.sh <project>`
  clones and builds it (not vendored here).
* Not every game used agbcc. Projects pick a compiler **profile** (`--compiler` on `init`,
  `--profile` on `match`); see [docs/compilers.md](docs/compilers.md). Includes
  `gcc-2.96-patched` for Camelot titles (Golden Sun): `scripts/install_camelot_gcc.sh` builds
  camelot-gcc in user space (verified on our box, see docs/compilers.md), not vendored.
* Games built with a compiler nobody can legally get (ARM ADS 1.2, e.g. the Webfoot DBZ titles)
  use `--compiler ads12`: **no matching**, an `asm-only` (rebuildable, for labelling) or
  `notes-only` (function table, no build) project instead.

## AI-assisted match loop (stub)
`gbadt/match.py` has the compile, compare and score parts. `propose()` is where you plug in a
model, giving it the target asm, a starting guess and the last diff. For a starting guess use
m2c's `-t gba` target (see `accel/skel.py` below) or Ghidra headless:
`scripts/ghidra_guess.sh rom.gba 0x08000108 thumb`.

## Speed-up tools for an existing decomp (`accel/`)
Scripts for grinding through functions in a project that already builds and compares
(one `.s` per function, `INCLUDE_ASM` lines in C files). They work on any project laid out
like that; nothing in them is tied to a game.

| Script | What it does |
|---|---|
| `cluster.py [--max-insns N] [--top K]` | groups functions by normalized asm shape (registers, immediates, symbols abstracted; `ldr =K` and `mov`+`lsl` both count as a constant). Families with a matched member (`*`) are listed first: that member's C is a ready template |
| `skel.py FUNC [-o out.c]` | m2c skeleton cleaned for matching: raw offsets instead of `M2C_FIELD`, signed `/ 2^k` restored, return type from the `pop {r0}`/`pop {r1}` tell |
| `mutate.py TU FUNC [start.c] [--budget S] [--keep]` | greedy hill-climb over semantics-preserving rewrites (operand order, declaration/statement order, signedness, loop forms, locals vs re-reads, index vs pointer, ...), scored by instruction diff against the original object |
| `auto.py [--budget S] FUNC...` | skeleton, then compile fixups, scoring and `mutate.py`, with one line of output per function. Keeps a match in place; otherwise restores the file and saves the best attempt |
| `permbatch.sh SECONDS TU:Func...` | runs decomp-permuter (-j1) on a list of near-misses in turn, starting from their current C |
| `funcutil.py get KEY` / `compare TU FUNC...` | the shared helpers: config, locating asm/C, splicing, building and diffing one object |
| `PLAYBOOK.md` | the ordered checklist and asm-to-C tells the tools automate |

**Config.** Copy `accel/accel.example.json` to `accel.json` (or pass `--config FILE`, or set
`$ACCEL_CONFIG`). It sets the project root, the asm/src directories, the build command for
one object (`{obj}`, `{tu}`, `{cc}`, `{cflags}` are substituted), the compiler and flags, where
the built object and the *reference* object live (`{stem}` = `src/dir/file`), objdump, an
optional env script, m2c and permuter paths, typedef names, and a scratch `work_dir` (timing
log, clusters, best attempts). The reference object is the same file built before your edit,
e.g. from a clean checkout of the project, so the tools never read the ROM.

**Requirements.** Python 3.8+, `pycparser`, ripgrep (`rg`), `arm-none-eabi-objdump`,
[m2c](https://github.com/matt-kempster/m2c) (`-t gba`),
[decomp-permuter](https://github.com/simonlindholm/decomp-permuter) for `permbatch.sh`, and the
project's own compiler (agbcc, or camelot gcc-2.96 via `scripts/install_camelot_gcc.sh`).

**Honest limits.**
* `mutate.py` narrows gaps (typically by a few diff lines) but rarely completes a match by
  itself. Over 28 runs on real near-misses it matched none.
* `permbatch.sh` doesn't handle overlays or other TUs the permuter can't compile standalone.
* On a camelot gcc-2.96 project the time per matched function went from about 2.7 to 1.5
  minutes (~1.8x) over a batch of about 10 functions. Almost all of that came from `cluster.py`
  plus reusing a matched sibling as a template, not from the mutator.
* The skeleton still needs hand fixes for duplicate declarations and struct types.

## Tests
`tests/run_tests.sh` builds the homebrew demo, runs `info`, `init`, `make compare` (OK), then
matches `checksum()` with the correct C (MATCH) and a wrong version (MISMATCH). It also builds
the demo a second time with a different layout (`demo_b.gba`, two extra functions) and checks
that signatures name all five shared functions there. If camelot
gcc-2.96 is installed, `tests/check_gcc296.py` also checks its codegen fingerprints.

## Legal notes (not legal advice)
Reverse engineering software you own for interoperability and study is broadly tolerated in
many places, but redistributing decompiled output or assets can infringe copyright. Rights
holders have issued takedowns even against projects that shipped no original bytes. Keep
it bring-your-own-ROM, keep your work clean-room (no leaked source), and expect the risk.

MIT licensed.

## Importing names from a sibling decomp

```
python3 -m gbadt import-symbols myproject sibling.syms [--offset 0x1234]
```
Takes `nm` output, linker-script `name = 0x...;` lines, or `0xADDR name` pairs and renames
any `sub_XXXXXXXX` whose start address matches. Unmatched symbols are reported, not applied.
The build stays byte-identical (tested in `tests/run_tests.sh`). Typical use: a game sharing
an engine with a finished project. Addresses rarely line up 1:1 across games, so pair functions
by signature first: `gbadt signatures match sibling.sigs myproject -o hits.syms` writes a file
`import-symbols` reads (see [docs/signatures.md](docs/signatures.md)).
