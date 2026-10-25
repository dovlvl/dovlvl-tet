"""Download only observed public game resources for local rules inspection.
Third-party game code is research input and is excluded from release ZIPs.
"""

from pathlib import Path
from urllib.request import urlopen
import json

ROOT = Path(__file__).resolve().parents[1] / "diagnostics/research"
URLS = {
    "main.js": "https://play.tetris.com/tetris-game-package/game/js/main.js?cbidg=62B1EB587D30B208-4ac25e5e",
    "import-map.json": "https://play.tetris.com/tetris-game-package/game/target-mobile/src/import-map.json?cbidg=62B1EB587D30B208",
    "index.js": "https://play.tetris.com/tetris-game-package/game/target-mobile/index.js?cbidg=62B1EB587D30B208",
}
if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, url in URLS.items():
        try:
            data = urlopen(url, timeout=25).read()
            (ROOT / name).write_bytes(data)
            manifest[name] = {"url": url, "bytes": len(data)}
        except Exception as exc:
            manifest[name] = {"url": url, "error": str(exc)}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest))
