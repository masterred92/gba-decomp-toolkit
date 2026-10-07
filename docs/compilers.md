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
| `gcc-2.96-patched` | see below ([Coaltergeist/camelot-gcc](https://github.com/Coaltergeist/camelot-gcc)) | `<project>/tools/gcc296` (`GCC296_DIR`) |
| `arm-none-eabi-gcc` | `scripts/install_toolchain.sh` | on `PATH` |

### gcc-2.96-patched (Camelot / Golden Sun)
```sh
sudo apt install -y build-essential binutils-arm-none-eabi python3 git
git clone https://github.com/Coaltergeist/camelot-gcc
cd camelot-gcc
./build.sh gcc296
./install.sh /path/to/your/project gcc296      # installs to <project>/tools/gcc296/
# or keep one shared copy and point at it:
export GCC296_DIR=$HOME/compilers/gcc296
```
It is a 2000-07-31 GCC 2.96 development snapshot, patched to build on modern Linux and to make
output deterministic (symbol hashing, zero-filled `.align`). The driver is `xgcc`; the toolkit
runs `xgcc -S` then `arm-none-eabi-as`. The flag set (`-fcall-used-r4`, `-fno-strict-aliasing`,
etc.) is copied from the goldensun-decomp Makefile as of 2026-10-07; check there if it changes.

## Adding a profile
Add an entry with `kind` (`cc1` = takes preprocessed C on stdin and emits asm, like agbcc;
`driver` = gcc-style driver), `cc`, `cflags`, `source`. `${VAR:-default}` is expanded.
