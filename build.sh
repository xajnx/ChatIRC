#!/usr/bin/env bash
set -euo pipefail

# Simple PyInstaller build wrapper (mirrors CI behavior)
APP=chatirc
ENTRY=chatirc.py
ICON_SRC=assets/appicon.png
ICON_ARG=""

if [[ "$(uname -s)" == "Darwin" ]]; then
	mkdir -p build/iconset
	sips -z 16 16 "$ICON_SRC" --out build/iconset/icon_16x16.png || true
	sips -z 32 32 "$ICON_SRC" --out build/iconset/icon_16x16@2x.png || true
	sips -z 32 32 "$ICON_SRC" --out build/iconset/icon_32x32.png || true
	sips -z 64 64 "$ICON_SRC" --out build/iconset/icon_32x32@2x.png || true
	sips -z 128 128 "$ICON_SRC" --out build/iconset/icon_128x128.png || true
	sips -z 256 256 "$ICON_SRC" --out build/iconset/icon_128x128@2x.png || true
	sips -z 256 256 "$ICON_SRC" --out build/iconset/icon_256x256.png || true
	sips -z 512 512 "$ICON_SRC" --out build/iconset/icon_256x256@2x.png || true
	sips -z 512 512 "$ICON_SRC" --out build/iconset/icon_512x512.png || true
	sips -z 1024 1024 "$ICON_SRC" --out build/iconset/icon_512x512@2x.png || true
	if command -v iconutil >/dev/null 2>&1; then
		mkdir -p build/icon
		iconutil -c icns build/iconset -o build/icon/appicon.icns || true
		if [[ -f build/icon/appicon.icns ]]; then
			ICON_ARG="--icon=build/icon/appicon.icns"
		fi
	fi
else
	if command -v convert >/dev/null 2>&1; then
		mkdir -p build/icon
		convert "$ICON_SRC" -resize 256x256 build/icon/appicon.ico || true
		if [[ -f build/icon/appicon.ico ]]; then
			ICON_ARG="--icon=build/icon/appicon.ico"
		fi
	fi
fi

pyinstaller --noconfirm --onefile $ICON_ARG --add-data "assets/appicon.png:assets" --add-data "assets/theme-classic.png:assets" --add-data "assets/theme-neon.png:assets" --add-data "assets/theme-glow.png:assets" --add-data "assets/theme-mono.png:assets" ${ENTRY}

echo "Build complete. See dist/"
