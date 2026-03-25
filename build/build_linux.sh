#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Building GridRunner for Linux..."
pip install . pyinstaller
pyinstaller build/gridrunner.spec --distpath dist/linux --workpath build/tmp --clean

echo "Build complete: dist/linux/GridRunner/"
