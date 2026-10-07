# Compiler profiles

A matching decomp only works with the *same* compiler the original developers used. Different
studios used different compilers, so each project picks a **profile** from
`compilers/profiles.json`.

```sh
python3 -m gbadt compilers                                   # list profiles
python3 -m gbadt init baserom.gba projects/mygame --compiler gcc-2.96-patched
python3 -m gbadt match projects/mygame sub_08001234 guess.c   # uses the project's profile
python3 -m gbadt match projects/mygame sub_08001234 guess.c --profile agbcc   # try another
```

`init` writes `"compiler"` into `config.json` and bakes the profile's `CC1`/`CFLAGS` into the
generated Makefile (override with `make CC1=... CFLAGS=...`). `--cc`/`--cflags` on `match` override
the profile for experiments.

## Nothing is vendored
The toolkit never ships compiler binaries or source. Each profile points to where you build it:

| Profile | Get it | Default location (override with env var) |
|---|---|---|
| `agbcc`, `old_agbcc` | `scripts/install_agbcc.sh <project>` ([pret/agbcc](https://github.com/pret/agbcc)) | `<project>/tools/agbcc` (`AGBCC_DIR`) |
| `gcc-2.96-patched` | `scripts/install_camelot_gcc.sh` ([Coaltergeist/camelot-gcc](https://github.com/Coaltergeist/camelot-gcc)) | `<project>/tools/gcc296`, or set `GCC296_DIR=~/tools/gcc296` |
| `arm-none-eabi-gcc` | `scripts/install_toolchain.sh` | on `PATH` |

### gcc-2.96-patched (Camelot / Golden Sun)
**Verified on our box on 2026-10-07** (Debian, host gcc 14.2, no sudo), camelot-gcc commit
`1197a54`. The build took under a minute on 8 cores.

```sh
scripts/install_camelot_gcc.sh                 # -> ~/tools/gcc296 (or pass another folder)
export GCC296_DIR=$HOME/tools/gcc296           # add to ~/.bashrc or tools/env.sh
python3 tests/check_gcc296.py                  # our own toy C: checks the Camelot fingerprints
```

What the script does, step by step, so you can do it by hand:
```sh
git clone --depth 1 https://github.com/Coaltergeist/camelot-gcc ~/src/camelot-gcc
cd ~/src/camelot-gcc
CXX=clang++ ./build.sh gcc296      # CXX only needed if g++ is missing (see "Gotcha" below)
mkdir -p /tmp/stage && ./install.sh /tmp/stage gcc296     # writes /tmp/stage/tools/gcc296
mv /tmp/stage/tools/gcc296 ~/tools/gcc296
python3 tests/run.py --compiler-dir ~/tools/gcc296        # camelot-gcc's own ROM-free tests
```
You get four programs: `xgcc` (the driver you call), `cc1` (the real C compiler), `cpp` and
`tradcpp` (preprocessors), plus `build-manifest.json` (hashes of what was built).

**Gotcha we hit:** `build.sh` first writes a provenance manifest that records the host C *and*
C++ compiler versions, and stops with `host compiler missing: g++` if there's no `g++`. The
gcc296 build compiles no C++, so pointing `CXX` at `clang++` is enough. (With admin rights,
`sudo apt install g++` also works.) `install.sh` wants a decomp checkout as its target, which
is why we install into a staging folder and move `tools/gcc296` out.

**How we know it works (no ROM needed):**
1. camelot-gcc's smoke corpus (`tests/run.py`): 3 fixtures (control flow, globals, padding), each
   compiled 3 times, must equal *exact* assembly captured from the compiler that rebuilt the full
   Golden Sun ROM. Result: `PASS` x3.
2. Our `tests/check_gcc296.py` compiles `tests/fixtures/camelot_toy.c` through the toolkit's own
   profile code and checks two Camelot fingerprints and determinism.

**Tutor's note: what the fingerprints look like.** Same C, two compilers:

```
int keep(int a, int b) { Notify(a); Notify(b); return a + b; }

camelot gcc-2.96                 modern arm-none-eabi-gcc 13
  push {r5, r6, lr}                push {r4, r5, r6, lr}
  adds r6, r1, #0                  movs r5, r1
  adds r5, r0, #0                  movs r4, r0
```
* gcc-2.96 never saves r4: `-fcall-used-r4` makes r4 a scratch register, so saved registers start
  at r5. If you see `push {r5, ...}` all over a ROM, think Camelot.
* Old GCC copies registers with `adds rX, rY, #0`; newer GCC writes `movs rX, rY`. Same effect,
  different bytes, which is exactly why the compiler version matters.
* `x * 10` becomes `lsls/adds/lsls` (shift-and-add), not a `mul`.

The profile's flag set (`-fcall-used-r4`, `-fno-strict-aliasing`, etc.) is copied from the
goldensun-decomp Makefile as of 2026-10-07; check there if it changes. The driver is `xgcc`; the
toolkit runs `xgcc -S` then `arm-none-eabi-as`, like the goldensun build. It is a 2000-07-31 GCC 2.96
development snapshot, patched to build on modern Linux and to make output deterministic (symbol
hashing by name, zero-filled `.align`).

## Adding a profile
Add an entry with `kind` (`cc1` = takes preprocessed C on stdin and emits asm, like agbcc;
`driver` = gcc-style driver), `cc`, `cflags`, `source`. `${VAR:-default}` is expanded.
