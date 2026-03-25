#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Building GridRunner for macOS..."
pip install . pyinstaller
pyinstaller build/gridrunner.spec --distpath dist/macos_raw --workpath build/tmp --clean

# Only keep the .app bundle for distribution
mkdir -p dist/macos
cp -R dist/macos_raw/GridRunner.app dist/macos/GridRunner.app
rm -rf dist/macos_raw

echo "Build complete: dist/macos/GridRunner.app"
