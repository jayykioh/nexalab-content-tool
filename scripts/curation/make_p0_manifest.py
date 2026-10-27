import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
base = root / "workspaces" / "khtn9-m1-real" / "exports" / "p0v2"
packs = []
for n in (11, 32, 40, 42, 43, 47):
    packs.append(json.loads((base / f"bai{n}" / "pack.authoring.json").read_text(encoding="utf-8"))["pack"])
out = base / "release-contract.json"
out.write_text(json.dumps({"name":"khtn9-p0-corrections-20261025","namespace":"baseline","sources":[],"packs":packs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(out)
