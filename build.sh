#!/usr/bin/env bash
# Install plugins from this repo into Krita's resource folder.
#
#   ./build.sh                 install every plugin
#   ./build.sh rebelsrule      install only the given folder(s)
#
# Each plugin lives in its own folder (folder name is free-form):
#   <folder>/<id>.desktop      plugin manifest (X-KDE-Library=<id>)
#   <folder>/<id>/             python package
#   <folder>/actions/*.action  optional shortcut definitions
#
# Restart Krita afterwards; it only loads Python plugins at startup.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
KRITA="${KRITA_RESOURCES:-$HOME/Library/Application Support/krita}"
PYKRITA="$KRITA/pykrita"
ACTIONS="$KRITA/actions"

if [ $# -gt 0 ]; then
  folders=("$@")
else
  folders=()
  for d in "$REPO"/*/; do
    ls "$d"/*.desktop >/dev/null 2>&1 && folders+=("$(basename "$d")")
  done
fi

mkdir -p "$PYKRITA" "$ACTIONS"

for folder in "${folders[@]}"; do
  src="$REPO/$folder"
  found=0
  for desktop in "$src"/*.desktop; do
    [ -f "$desktop" ] || continue
    id="$(basename "$desktop" .desktop)"
    if [ ! -d "$src/$id" ]; then
      echo "skip: $folder/$id.desktop (no $folder/$id/ package)" >&2
      continue
    fi
    cp "$desktop" "$PYKRITA/"
    rsync -a --delete --exclude __pycache__ "$src/$id/" "$PYKRITA/$id/"
    found=1
    echo "installed: $folder ($id)"
  done
  if [ "$found" = 0 ]; then
    echo "skip: $folder (no <id>.desktop + <id>/ package)" >&2
    continue
  fi
  if [ -d "$src/actions" ]; then
    cp "$src"/actions/*.action "$ACTIONS/" 2>/dev/null || true
  fi
done

echo "Restart Krita to load the changes."
