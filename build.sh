#!/usr/bin/env bash
# Install plugins from this repo into Krita's resource folder.
#
#   ./build.sh                    link every plugin (development, the default):
#                                 edits in the repo are live in Krita, and
#                                 plugins that support it reload themselves
#                                 on save - no need to re-run this script
#   ./build.sh rebelsrule         link only the given folder(s)
#   ./build.sh --copy [folders]   copy instead of link, e.g. for a stable
#                                 install that doesn't follow repo edits
#   ./build.sh --uninstall [folders]
#                                 remove the plugins from Krita, whether
#                                 linked, copied or imported from a zip
#                                 (e.g. before testing a zip import)
#   ./build.sh --zip [folders]    build release zips in dist/ for Krita's
#                                 Tools > Scripts > Import Python Plugin
#                                 from File... (no dev files included)
#
# Each plugin lives in its own folder (folder name is free-form):
#   <folder>/<id>.desktop      plugin manifest (X-KDE-Library=<id>)
#   <folder>/<id>/             python package
#   <folder>/actions/*.action  optional shortcut definitions; files ending in
#                              -dev.action are only installed when linking
#   <folder>/<id>/Manual.src.html
#                              optional manual source; built into Manual.html
#                              with images embedded (see build_manual below)
#
# Linking also drops a `.dev` marker in each package so plugins can turn on
# dev-only features (reload action, auto-reload, .dev.log). --copy leaves the
# marker, logs, manual sources and -dev.action files out.
#
# Restart Krita after the first install, and whenever a .desktop or
# .action file changes; Krita only reads those at startup.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
KRITA="${KRITA_RESOURCES:-$HOME/Library/Application Support/krita}"
PYKRITA="$KRITA/pykrita"
ACTIONS="$KRITA/actions"

link=1
zip=0
uninstall=0
case "${1:-}" in
  --copy) link=0; shift ;;
  --zip)  link=0; zip=1; shift ;;
  --uninstall) uninstall=1; shift ;;
  --link) shift ;;   # the default; still accepted
esac

if [ $# -gt 0 ]; then
  folders=("$@")
else
  folders=()
  for d in "$REPO"/*/; do
    ls "$d"/*.desktop >/dev/null 2>&1 && folders+=("$(basename "$d")")
  done
fi

reload_hints=()

# Uninstall: remove each plugin's manifest, package and .action files from
# Krita, however they got there. `rm -rf` on a path without a trailing
# slash removes a link itself, never the repo folder it points to.
if [ "$uninstall" = 1 ]; then
  pgrep -xq krita && echo "note: Krita is running; quit it so it doesn't keep the old plugin loaded." >&2
  for folder in "${folders[@]}"; do
    src="$REPO/$folder"
    for desktop in "$src"/*.desktop; do
      [ -f "$desktop" ] || continue
      id="$(basename "$desktop" .desktop)"
      removed=0
      for path in "$PYKRITA/$id" "$PYKRITA/$id.desktop"; do
        if [ -e "$path" ] || [ -L "$path" ]; then rm -rf "$path"; removed=1; fi
      done
      for action in "$src"/actions/*.action; do
        [ -f "$action" ] || continue
        path="$ACTIONS/$(basename "$action")"
        if [ -e "$path" ] || [ -L "$path" ]; then rm -f "$path"; removed=1; fi
      done
      if [ "$removed" = 1 ]; then echo "uninstalled: $folder ($id)"; else echo "not installed: $folder ($id)"; fi
    done
  done
  echo "Run ./build.sh to install the dev version again."
  exit 0
fi


mkdir -p "$PYKRITA" "$ACTIONS"

# Krita gives a plugin's manual to Qt as plain text with no base folder, so
# relative <img src="x.png"> paths don't resolve. Turn every relative image
# in Manual.src.html into an embedded data: URI and write Manual.html.
build_manual() {
  local pkg="$1"
  [ -f "$pkg/Manual.src.html" ] || return 0
  python3 - "$pkg" <<'PY'
import base64, mimetypes, os, re, sys
pkg = sys.argv[1]
src = open(os.path.join(pkg, "Manual.src.html"), encoding="utf-8").read()

def embed(m):
    path = os.path.join(pkg, m.group(2))
    if re.match(r"^[a-z]+:", m.group(2)) or not os.path.isfile(path):
        return m.group(0)
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    data = base64.b64encode(open(path, "rb").read()).decode()
    return f'{m.group(1)}data:{mime};base64,{data}{m.group(3)}'

# Drop comments first so commented-out images aren't embedded for nothing.
src = re.sub(r"<!--.*?-->\n?", "", src, flags=re.S)
out = re.sub(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', embed, src)
# The note goes at the end: Krita lets Qt guess whether the manual is HTML,
# and Qt only says yes if the file starts with a real tag, not a comment.
note = "\n<!-- Generated from Manual.src.html by build.sh - edit that file instead. -->\n"
open(os.path.join(pkg, "Manual.html"), "w", encoding="utf-8").write(out.rstrip() + "\n" + note)
PY
}

# Copy or symlink $1 to $2, replacing whatever is there (file, dir or link).
# Removing first matters: copying into a symlink would write into the repo.
install_path() {
  local src="$1" dest="$2"
  if [ "$link" = 0 ] && [ -d "$src" ] && [ -L "$dest" ]; then
    echo "note: $(basename "$dest") was linked; it's now a copy, so edits and" >&2
    echo "      auto-reload won't reach Krita. Run ./build.sh without --copy to develop." >&2
  fi
  rm -rf "$dest"
  if [ "$link" = 1 ]; then
    ln -s "$src" "$dest"
  elif [ -d "$src" ]; then
    rsync -a --exclude __pycache__ --exclude .dev --exclude .dev.log \
      --exclude Manual.src.html "$src/" "$dest/"
  else
    cp "$src" "$dest"
  fi
}

# Release zip: the layout Krita's plugin importer expects -
# <id>.desktop, <id>/ (with __init__.py) and <id>.action at the top level.
if [ "$zip" = 1 ]; then
  mkdir -p "$REPO/dist"
  for folder in "${folders[@]}"; do
    src="$REPO/$folder"
    for desktop in "$src"/*.desktop; do
      [ -f "$desktop" ] || continue
      id="$(basename "$desktop" .desktop)"
      [ -d "$src/$id" ] || continue
      build_manual "$src/$id"
      stage="$(mktemp -d)"
      cp "$desktop" "$stage/"
      rsync -a --exclude __pycache__ --exclude .dev --exclude .dev.log \
        --exclude Manual.src.html --exclude '*.svg' "$src/$id/" "$stage/$id/"
      [ -f "$src/actions/$id.action" ] && cp "$src/actions/$id.action" "$stage/"
      out="$REPO/dist/$id.zip"
      rm -f "$out"
      (cd "$stage" && zip -qr "$out" .)
      rm -rf "$stage"
      echo "zipped: $folder -> dist/$id.zip"
    done
  done
  exit 0
fi

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
    build_manual "$src/$id"
    if [ "$link" = 1 ]; then
      touch "$src/$id/.dev"
    else
      rm -f "$src/$id/.dev"   # also turns dev mode off for an old link
    fi
    install_path "$desktop" "$PYKRITA/$id.desktop"
    install_path "$src/$id" "$PYKRITA/$id"
    found=1
    echo "$([ "$link" = 1 ] && echo linked || echo installed): $folder ($id)"
  done
  if [ "$found" = 0 ]; then
    echo "skip: $folder (no <id>.desktop + <id>/ package)" >&2
    continue
  fi
  for action in "$src"/actions/*.action; do
    [ -f "$action" ] || continue
    if [ "$link" = 0 ] && [[ "$action" == *-dev.action ]]; then
      rm -f "$ACTIONS/$(basename "$action")"
      continue
    fi
    install_path "$action" "$ACTIONS/$(basename "$action")"
    # Collect "<text> (<shortcut>)" for any action whose name mentions reload.
    if [ "$link" = 1 ]; then
      while IFS= read -r hint; do
        reload_hints+=("$folder: $hint")
      done < <(awk '
        /<Action name=/ { inact = tolower($0) ~ /reload/; text = ""; key = "" }
        inact && /<text>/     { gsub(/.*<text>|<\/text>.*/, ""); text = $0 }
        inact && /<shortcut>/ { gsub(/.*<shortcut>|<\/shortcut>.*/, "")
                                n = split($0, k, "+"); key = ""
                                for (i = 1; i <= n; i++) key = key (i > 1 ? "+" : "") toupper(substr(k[i],1,1)) substr(k[i],2) }
        inact && /<\/Action>/ { print text (key != "" ? " (" key ")" : ""); inact = 0 }
      ' "$action")
    fi
  done
done

echo "Restart Krita if this is a first install or a .desktop/.action file changed."

if [ "$link" = 1 ]; then
  echo
  if [ ${#reload_hints[@]} -gt 0 ]; then
    echo "Hot reload: plugins with a reload action watch their own .py files and"
    echo "reload when you save. To reload by hand, use Tools > Scripts >"
    for hint in "${reload_hints[@]}"; do
      echo "  $hint"
    done
  else
    echo "Hot reload: none of these plugins defines a reload action; restart Krita to see edits."
  fi
fi
