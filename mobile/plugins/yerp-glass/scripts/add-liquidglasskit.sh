#!/usr/bin/env bash
# Copies LiquidGlassKit (MIT, https://github.com/muhittincamdali/LiquidGlassKit) at a pinned release into this plugin, so
# CocoaPods compiles it with the plugin. Run from anywhere; used by the iOS job in .github/workflows/mobile-build.yml.
set -euo pipefail
TAG="${LIQUIDGLASSKIT_TAG:-v2.1.0}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
git clone --quiet --depth 1 --branch "$TAG" https://github.com/muhittincamdali/LiquidGlassKit.git "$TMP/lgk"
rm -rf "$HERE/ios/Sources/LiquidGlassKit"
mkdir -p "$HERE/ios/Sources/LiquidGlassKit"
# Swift sources only (the package also holds docs, tests and examples).
(cd "$TMP/lgk/Sources/LiquidGlassKit" && find . -name '*.swift' -print0 | while IFS= read -r -d '' f; do
  mkdir -p "$HERE/ios/Sources/LiquidGlassKit/$(dirname "$f")"
  cp "$f" "$HERE/ios/Sources/LiquidGlassKit/$f"
done)
cp "$TMP/lgk/LICENSE" "$HERE/ios/LICENSE-LiquidGlassKit"
echo "LiquidGlassKit $TAG: $(find "$HERE/ios/Sources/LiquidGlassKit" -name '*.swift' | wc -l | tr -d ' ') Swift files"
