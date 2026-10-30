"""Maintainer step: unpack a contributed submission into results/raw/<name>/, ready for grade.py.

    python3 scripts/ingest.py submissions/<file>.json [...]
Then: python3 scripts/grade.py --once ; python3 scripts/build_site.py
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import garble  # noqa: E402

for f in sys.argv[1:]:
    problems = garble.verify(f)
    if problems:
        sys.exit(f"{f}: refusing, " + "; ".join(problems))
    s = json.loads(Path(f).read_text())
    out = ROOT / "results/raw" / s["name"]
    if out.exists():
        sys.exit(f"{out} exists: pick another --name or remove it first")
    out.mkdir(parents=True)
    for iid, r in s["replies"].items():
        r.update({"config": s["name"], "model": s["model"], "effort": s["effort"], "item": iid,
                  "harness": s["harness"], "contributor": s["contributor"]})
        r.pop("id", None)
        (out / f"{iid}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    print(f"{s['name']}: 288 replies from {s['contributor']} via {s['harness']} -> {out.relative_to(ROOT)}")
    print("  add the model to NAMES / colours in scripts/build_site.py and site/app.js if it is new")
