#!/usr/bin/env bash
set -euo pipefail

# Simple PyInstaller build wrapper
APP=chatirc
ENTRY=chatirc.py

pyinstaller --onefile --name ${APP} ${ENTRY}

echo "Build complete. See dist/${APP}"
