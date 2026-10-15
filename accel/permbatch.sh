#!/bin/bash
# permbatch.sh [--config accel.json] SECONDS TU:Func [TU:Func ...]
# Runs decomp-permuter on each near-miss in turn (-j1), using the function's current C
# in TU as the base. Prints the best score per function; permuter output stays in
# <repo>/nonmatchings/<Func> (delete it when done). Log: <work_dir>/permbatch.log
# Limit: decomp-permuter's import.py must be able to compile the TU on its own, which
# fails for TUs that need extra build steps (e.g. overlays linked at another address).
set -u
here=$(cd "$(dirname "$0")" && pwd)
cfg=(); [ "${1:-}" = --config ] && { cfg=(--config "$2"); shift 2; }
get(){ python3 "$here/funcutil.py" "${cfg[@]}" get "$1"; }
repo=$(get repo); perm=$(get permuter); work=$(get work_dir); asm=$(get asm_dir)
fs=$(get func_start); envs=$(get env_script)
[ -n "$envs" ] && source "${envs/#\~/$HOME}" >/dev/null 2>&1
[ -d "$perm" ] || { echo "set \"permuter\" in the config to a decomp-permuter checkout"; exit 1; }
t=$1; shift; cd "$repo" || exit 1
for x in "$@"; do
  tu=${x%%:*}; f=${x##*:}; s=$(date +%s)
  a=$(rg -l "$fs $f\b" "$asm" | head -1)
  { echo "glabel $f"; grep -vE "^\s*\.include|$fs|func_end" "$a"; } > "$work/perm_$f.s"
  rm -rf "nonmatchings/$f"
  if timeout 200 python3 "$perm/import.py" "$tu" "$work/perm_$f.s" > "$work/perm_import_$f.log" 2>&1; then
    d=$(ls -d nonmatchings/$f* | head -1)
    # drop asm includes the permuter cannot compile
    sed -i "/__asm__(\".include/d; /^_permuter_ignore_line __asm__/d" "$d/base.c"
    sed -i -E "s/ _permuter_ignore_line __asm__\(\"[^\"]*\"\)//; s/ __asm__\(\"[^\"]*\"\);/;/" "$d/base.c"
    timeout "$t" python3 "$perm/permuter.py" "$d" -j1 --stop-on-zero > "$work/perm_$f.log" 2>&1
    best=$(ls -d "$d"/output-* 2>/dev/null | sed -E 's/.*output-([0-9]+)-.*/\1/' | sort -n | head -1)
    base=$(grep -m1 -oE "base score = [0-9]+" "$work/perm_$f.log" | grep -oE "[0-9]+$")
  else best=import-failed; base=; fi
  echo "$(date +%F' '%T) $f base=${base:-?} best=${best:-none} secs=$(( $(date +%s)-s ))" | tee -a "$work/permbatch.log"
done
