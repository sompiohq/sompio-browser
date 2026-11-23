#!/bin/sh
# Builds the browser-store packages from extension/:
#   dist/sompio-vault-<v>-chrome.zip   Chrome Web Store and Edge Add-ons
#   dist/sompio-vault-<v>-firefox.zip  addons.mozilla.org
# The stores don't accept the "key" used for loading it by hand, Chrome wants only a service worker,
# and Firefox only background scripts.
set -e
cd "$(dirname "$0")"
out=dist; mkdir -p "$out"
v=$(python3 -c "import json;print(json.load(open('extension/manifest.json'))['version'])")
for target in chrome firefox; do
  tmp=$(mktemp -d)
  cp -r extension/. "$tmp/"
  python3 - "$tmp/manifest.json" "$target" <<'PY'
import json, sys
p, target = sys.argv[1], sys.argv[2]
m = json.load(open(p))
m.pop("key", None)
if target == "chrome":
    m["background"] = {"service_worker": m["background"]["service_worker"]}
    m.pop("browser_specific_settings", None)
else:
    m["background"] = {"scripts": m["background"]["scripts"]}
    g = m["browser_specific_settings"]["gecko"]
    g["strict_min_version"] = "140.0"
    g["data_collection_permissions"] = {"required": ["none"]}
json.dump(m, open(p, "w"), indent=2, ensure_ascii=False)
PY
  rm -f "$out/sompio-vault-$v-$target.zip"
  (cd "$tmp" && zip -q -X -r - . -x '.*') > "$out/sompio-vault-$v-$target.zip"
  rm -rf "$tmp"
  echo "$out/sompio-vault-$v-$target.zip"
done
