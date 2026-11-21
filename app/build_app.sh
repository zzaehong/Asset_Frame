#!/bin/sh
# Builds app/build/AssetFrame.app (ad-hoc signed, for this Mac only) with this repo as its project folder.
# --install also copies it to ~/Applications so it opens from Launchpad/Spotlight/Finder like any app.
set -eu
cd "$(dirname "$0")"
root="$(cd .. && pwd)"
swift build -c release
bin="$(swift build -c release --show-bin-path)"
app="build/AssetFrame.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp "$bin/AssetFrame" "$app/Contents/MacOS/AssetFrame"
cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Asset Frame</string>
  <key>CFBundleDisplayName</key><string>Asset Frame</string>
  <key>CFBundleIdentifier</key><string>local.assetframe.app</string>
  <key>CFBundleExecutable</key><string>AssetFrame</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>AssetFrameHome</key><string>$root</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$app"
echo "built $app"
if [ "${1:-}" = "--install" ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/AssetFrame.app"
  ditto "$app" "$HOME/Applications/AssetFrame.app"
  echo "installed $HOME/Applications/AssetFrame.app"
fi
