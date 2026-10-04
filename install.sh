#!/usr/bin/env bash
# DevSweep installer: adds the app to the application menu and a `devsweep` command.
#   ./install.sh              install (no root needed)
#   ./install.sh --uninstall  remove
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP="$APPS/io.github.aFeruz.DevSweep.desktop"
BIN="$HOME/.local/bin/devsweep"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$DESKTOP" "$BIN" "$APPS/storage-cleaner.desktop"
  update-desktop-database "$APPS" 2>/dev/null || true
  echo "✓ DevSweep removed. Settings are kept in ~/.config/devsweep (delete manually if you want)."
  exit 0
fi

command -v python3 >/dev/null || { echo "✗ python3 not found"; exit 1; }

if ! python3 - <<'PY' 2>/dev/null
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw
assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 5)
PY
then
  echo "⚠ GTK 4 / libadwaita 1.5+ not found — the desktop app won't start (the browser UI still works)."
  echo "  Ubuntu/Debian: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
  echo "  Fedora:        sudo dnf install python3-gobject gtk4 libadwaita"
  echo "  Arch:          sudo pacman -S python-gobject gtk4 libadwaita"
fi

mkdir -p "$APPS" "$(dirname "$BIN")"
rm -f "$APPS/storage-cleaner.desktop"  # old name

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=DevSweep
Comment=Clean Docker leftovers, caches, duplicates and large files safely
Comment[ru]=Безопасная очистка остатков Docker, кэшей, дубликатов и больших файлов
Comment[uz]=Docker qoldiqlari, keshlar, dublikat va katta fayllarni xavfsiz tozalash
Exec=python3 "$DIR/gui.py"
Icon=user-trash-full
Terminal=false
Categories=Utility;
Keywords=disk;clean;cache;docker;junk;очистка;диск;tozalash;
StartupWMClass=io.github.aFeruz.DevSweep
EOF

cat > "$BIN" <<EOF
#!/usr/bin/env bash
# devsweep          → desktop app
# devsweep --web    → browser UI (http://127.0.0.1:8765)
if [[ "\${1:-}" == "--web" ]]; then shift; exec python3 "$DIR/cleaner.py" "\$@"; fi
exec python3 "$DIR/gui.py" "\$@"
EOF
chmod +x "$BIN"
update-desktop-database "$APPS" 2>/dev/null || true

echo "✓ DevSweep installed"
echo "  • App menu: press Super and type \"DevSweep\""
echo "  • Terminal: devsweep   (browser UI: devsweep --web)"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "  ⚠ ~/.local/bin is not in PATH — add it to use the devsweep command";; esac
