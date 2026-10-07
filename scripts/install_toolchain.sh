#!/usr/bin/env bash
# User-space ARM GNU toolchain (no root needed).
set -euo pipefail
V=13.3.rel1; D="$HOME/tools/arm-gnu-toolchain-$V-x86_64-arm-none-eabi"
if [ ! -x "$D/bin/arm-none-eabi-as" ]; then
  mkdir -p "$HOME/tools"; cd "$HOME/tools"
  curl -L -o arm.tar.xz "https://developer.arm.com/-/media/Files/downloads/gnu/$V/binrel/arm-gnu-toolchain-$V-x86_64-arm-none-eabi.tar.xz"
  python3 -c "import tarfile;tarfile.open('arm.tar.xz').extractall()"; rm arm.tar.xz
fi
mkdir -p "$HOME/.local/bin"; ln -sf "$D"/bin/arm-none-eabi-* "$HOME/.local/bin/"
arm-none-eabi-as --version | head -1
