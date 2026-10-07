#!/usr/bin/env bash
# Build Camelot's patched GCC 2.96 (Golden Sun) in user space. No sudo, nothing vendored.
#   scripts/install_camelot_gcc.sh [dest]        default dest: ~/tools/gcc296
# Then: export GCC296_DIR=<dest>   (the gcc-2.96-patched profile reads it)
# Needs: git, python3, make, a host C compiler (gcc). camelot-gcc's build records a C++
# compiler in its provenance manifest but compiles no C++ for gcc296; if g++ is missing we
# point CXX at clang++ (or c++) so the manifest step succeeds.
set -euo pipefail
DEST="$(realpath -m "${1:-$HOME/tools/gcc296}")"
SRC="${CAMELOT_GCC_SRC:-$HOME/src/camelot-gcc}"
[ -d "$SRC" ] || git clone --depth 1 https://github.com/Coaltergeist/camelot-gcc "$SRC"
if [ -z "${CXX:-}" ] && ! command -v g++ >/dev/null; then
  for c in clang++ c++; do command -v "$c" >/dev/null && { export CXX="$c"; break; }; done
fi
( cd "$SRC" && ./build.sh gcc296 )
# install.sh expects a decomp checkout and writes <dir>/tools/gcc296; stage, then move.
STAGE="$(mktemp -d)"
( cd "$SRC" && ./install.sh "$STAGE" gcc296 )
mkdir -p "$(dirname "$DEST")" && rm -rf "$DEST" && mv "$STAGE/tools/gcc296" "$DEST" && rm -rf "$STAGE"
# ROM-free smoke corpus shipped with camelot-gcc: exact asm vs the production compiler's baseline.
( cd "$SRC" && python3 tests/run.py --compiler-dir "$DEST" )
echo "camelot gcc-2.96 installed in $DEST  ->  export GCC296_DIR=$DEST"
