#!/bin/bash
# Install fix-my-scaling for the current user:
#   ~/.local/share/fix-my-scaling   program files
#   ~/.local/bin/fix-my-scaling     command
#   ~/.local/share/applications     app launcher entry (Super + Space)
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DATA/fix-my-scaling"
BIN="$HOME/.local/bin"

for cmd in python3 hyprctl; do
  command -v "$cmd" >/dev/null || { echo "Missing: $cmd"; exit 1; }
done

mkdir -p "$DEST" "$BIN" "$DATA/applications"
install -m 755 "$SRC/fix-my-scaling.py" "$DEST/fix-my-scaling.py"
install -m 644 "$SRC/index.html" "$DEST/index.html"

cat >"$BIN/fix-my-scaling" <<SH
#!/bin/bash
exec python3 "$DEST/fix-my-scaling.py" "\$@"
SH
chmod 755 "$BIN/fix-my-scaling"

sed "s|@BIN@|$BIN|" "$SRC/fix-my-scaling.desktop" >"$DATA/applications/fix-my-scaling.desktop"
update-desktop-database "$DATA/applications" 2>/dev/null || true

echo "Installed fix-my-scaling."
echo "Open it from the app launcher (Super + Space → \"Fix My Scaling\") or run: fix-my-scaling"
