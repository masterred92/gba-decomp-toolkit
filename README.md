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

## AI-assisted match loop (stub)
`gbadt/match.py` has the compile, compare and score parts. `propose()` is where you plug in a
model, giving it the target asm, a starting guess and the last diff. **m2c has no ARM backend**,
so the starting guess comes from Ghidra headless: `scripts/ghidra_guess.sh rom.gba 0x08000108 thumb`.

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
