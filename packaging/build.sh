#!/usr/bin/env bash
# Build Cable Designer on macOS (dist/CableDesigner.app) or Linux (dist/CableDesigner).
# Run from the repository root:   ./packaging/build.sh
set -euo pipefail
python3 -m venv .venv-build
.venv-build/bin/python -m pip install --upgrade pip
.venv-build/bin/python -m pip install -r requirements-desktop.txt pyinstaller
.venv-build/bin/pyinstaller packaging/cable_designer.spec --noconfirm --clean
if [[ "$(uname)" == "Darwin" ]]; then
  BIN=dist/CableDesigner.app/Contents/MacOS/CableDesigner
else
  BIN=dist/CableDesigner
fi
QT_QPA_PLATFORM=offscreen "$BIN" --smoke-test dist/smoke-test
echo "Built $BIN"
