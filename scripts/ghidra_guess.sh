#!/usr/bin/env bash
# Starting C guess for one function via Ghidra headless (m2c has no ARM backend).
# Usage: ghidra_guess.sh baserom.gba 0x080001F0 [thumb|arm]
set -euo pipefail
ROM=$1; ADDR=$2; MODE=${3:-thumb}
GH=${GHIDRA_HOME:?set GHIDRA_HOME}; TMP=$(mktemp -d)
cat > "$TMP/Guess.java" <<J
import ghidra.app.script.GhidraScript; import ghidra.app.decompiler.*;
public class Guess extends GhidraScript { public void run() throws Exception {
  var a = toAddr(Long.decode("$ADDR"));
  if ("$MODE".equals("thumb")) { var r = currentProgram.getRegister("TMode");
    currentProgram.getProgramContext().setValue(r, a, a, java.math.BigInteger.ONE); }
  disassemble(a); var f = getFunctionAt(a); if (f == null) f = createFunction(a, null);
  var d = new DecompInterface(); d.openProgram(currentProgram);
  println(d.decompileFunction(f, 60, monitor).getDecompiledFunction().getC()); } }
J
"$GH/support/analyzeHeadless" "$TMP" p -import "$ROM" -processor ARM:LE:32:v4t \
  -loader BinaryLoader -loader-baseAddr 0x08000000 -scriptPath "$TMP" -postScript Guess.java -deleteProject \
  2>&1 | sed -n '/Guess.java>/,$p'
