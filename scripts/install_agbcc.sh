#!/usr/bin/env bash
# Fetch and build pret/agbcc (GCC 2.95-era compiler used by many GBA titles).
# Not vendored here. Usage: scripts/install_agbcc.sh <project_dir>
set -euo pipefail
P="${1:?project dir}"; W="${AGBCC_SRC:-$HOME/tools/agbcc}"
[ -d "$W" ] || git clone https://github.com/pret/agbcc "$W"
( cd "$W" && ./build.sh )
( cd "$W" && ./install.sh "$(realpath "$P")" )   # installs into $P/tools/agbcc
