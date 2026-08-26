#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
VERSION="$(cat "$ROOT/VERSION")"
APP="$HOME/Desktop/筱宇智矩-${VERSION}.app"
CURRENT="$HOME/Downloads/zhiju-runtime-current"

find "$HOME/Desktop" -maxdepth 1 -type d \( -name '筱宇智矩.app' -o -name '筱宇智矩-*.app' \) -exec rm -rf {} +
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat >"$APP/Contents/Resources/start-package.command" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

CURRENT_ROOT="$HOME/Downloads/zhiju-runtime-current"
if [[ ! -f "$CURRENT_ROOT/VERSION" || ! -f "$CURRENT_ROOT/scripts/start_package.sh" ]]; then
  echo "[筱宇智矩] 当前运行包缺失或不完整：$CURRENT_ROOT" >&2
  read -r -p "按回车键关闭..." _ || true
  exit 1
fi

echo "[筱宇智矩] 正在启动运行包：$(cat "$CURRENT_ROOT/VERSION")"
exec bash "$CURRENT_ROOT/scripts/start_package.sh"
EOF
chmod +x "$APP/Contents/Resources/start-package.command"

cat >"$APP/Contents/MacOS/launcher" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
CONTENTS_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
exec /usr/bin/open -a Terminal "$CONTENTS_DIR/Resources/start-package.command"
EOF
chmod +x "$APP/Contents/MacOS/launcher"

cat >"$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleDisplayName</key><string>筱宇智矩-${VERSION}</string>
<key>CFBundleExecutable</key><string>launcher</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundleIdentifier</key><string>local.xiaoyu.zhiju.runtime.${VERSION}</string>
<key>CFBundleName</key><string>筱宇智矩-${VERSION}</string>
<key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>
EOF

ICON_SOURCE="$ROOT/assets/app-icon-1024.png"
if [[ -f "$ICON_SOURCE" ]]; then
  ICONSET="$(mktemp -d -t zhiju-icon.XXXXXX)/zhiju.iconset"
  mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$ICON_SOURCE" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$ICON_SOURCE" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
  rm -rf "$(dirname "$ICONSET")"
fi

touch "$APP"
echo "[筱宇智矩] 桌面应用已创建：$APP"
