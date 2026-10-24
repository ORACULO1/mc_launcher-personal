"""Cambia la versión en todos los sitios a la vez:  python scripts/bump_version.py 2.0.1"""
import json
import re
import sys
from pathlib import Path

if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
    sys.exit("Uso: python scripts/bump_version.py 2.0.1")
v = sys.argv[1]
root = Path(__file__).resolve().parent.parent

for rel in ("src-tauri/tauri.conf.json", "package.json"):
    p = root / rel
    data = json.loads(p.read_text(encoding="utf-8"))
    data["version"] = v
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

p = root / "src-tauri/Cargo.toml"
p.write_text(re.sub(r'(?m)^version = ".*"', f'version = "{v}"', p.read_text(encoding="utf-8"), count=1), encoding="utf-8")

p = root / "backend/updater.py"
p.write_text(re.sub(r'CURRENT_VERSION = ".*"', f'CURRENT_VERSION = "{v}"', p.read_text(encoding="utf-8")), encoding="utf-8")
p = root / "src-tauri/Cargo.lock"
t = p.read_text(encoding="utf-8")
p.write_text(re.sub(r'(name = "chechenitza-studio"\nversion = ")[^"]*"', r'\g<1>' + v + '"', t), encoding="utf-8")

p = root / "scripts/build-backend.bat"
t = p.read_text(encoding="utf-8")
p.write_text(re.sub(r"(--(?:file|product)-version=)[\d.]+", r"\g<1>" + v + ".0", t), encoding="utf-8")
print("Versión actualizada a", v)
