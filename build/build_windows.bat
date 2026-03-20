@echo off
cd /d "%~dp0\.."

echo Building GridRunner for Windows...
pip install -r requirements.txt pyinstaller
pyinstaller build\gridrunner.spec --distpath dist\windows --workpath build\tmp --clean

echo Build complete: dist\windows\GridRunner\GridRunner.exe
