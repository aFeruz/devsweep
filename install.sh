#!/usr/bin/env bash
# DevSweep'ni ilovalar menyusiga qo'shadi (Super tugmasi → "Storage Cleaner")
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/applications/storage-cleaner.desktop"

python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')" 2>/dev/null || {
  echo "GTK4/libadwaita topilmadi. O'rnating: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
  exit 1
}

mkdir -p "$(dirname "$DEST")"
cat > "$DEST" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Storage Cleaner
Comment=Keraksiz fayllar, keshlar va Docker qoldiqlarini tozalash
Exec=python3 "$DIR/gui.py"
Icon=user-trash-full
Terminal=false
Categories=Utility;
Keywords=disk;clean;cache;docker;tozalash;
StartupWMClass=uz.feruz.StorageCleaner
DESKTOP
update-desktop-database "$(dirname "$DEST")" 2>/dev/null || true
echo "✓ O'rnatildi: $DEST"
