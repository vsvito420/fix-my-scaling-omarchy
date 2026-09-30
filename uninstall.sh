#!/bin/bash
# Remove fix-my-scaling. Your monitors.lua and its backups are left untouched.
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -rf "$DATA/fix-my-scaling" "${XDG_CACHE_HOME:-$HOME/.cache}/fix-my-scaling-chromium"
rm -f "$HOME/.local/bin/fix-my-scaling" "$DATA/applications/fix-my-scaling.desktop"
update-desktop-database "$DATA/applications" 2>/dev/null || true
echo "Removed fix-my-scaling."
