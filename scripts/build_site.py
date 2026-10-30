"""Aggregate raw responses + grades into site/data.json."""
import json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, GR = ROOT / "results/raw", ROOT / "results/grades"
NAMES = {"sol": "GPT-6.1 Sol", "terra": "GPT-6.1 Terra", "astra": "GPT-6 Astra", "luna": "GPT-6 Luna",
         "argon": "Gemini 4 Argon", "flash": "Gemini 3.8 Flash",
         "grok": "Grok 4.7"}
EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"]


def outcome(g):
    b = g["behavior"]
    if b == "error":
        return "error"
    if b in ("answered", "confirmed"):
        return ("right" if b == "answered" else "checked") if g["correct"] else "wrong"
    return b  # guessed / lost


def build():
    d = json.loads((ROOT / "data/items.json").read_text())
    rates, items = d["rates"], d["items"]
    qs = {}
    for it in items:
        q = qs.setdefault(it["qid"], {"id": it["qid"], "question": it["question"], "answer": it["answer"], "prompts": []})
        q["prompts"].append(it["prompt"])
    configs = []
    for cdir in sorted(RAW.iterdir()) if RAW.exists() else []:
        if not cdir.is_dir():
            continue
        m, e = cdir.name.rsplit("-", 1)
        res, ran = {}, 0
        for it in items:
            f = cdir / f"{it['id']}.json"
            if not f.exists():
                continue
            ran += 1
            g = GR / f"{cdir.name}__{it['id']}.json"
            if not g.exists():
                continue
            r, gg = json.loads(f.read_text()), json.loads(g.read_text())
            u = r.get("usage") or {}
            res[it["id"]] = {"o": outcome(gg), "n": gg.get("note", ""), "r": (r.get("response") or "")[:700],
                             "s": r.get("seconds"), "t": (u.get("output_tokens") or 0)}
        acc, phases = [], []
        for li in range(len(rates)):
            row = [res.get(f"{q}-L{li:02d}") for q in qs]
            row = [x for x in row if x]
            ok = sum(x["o"] in ("right", "checked") for x in row)
            acc.append(round(ok / len(row), 4) if row else None)
            cnt = {}
            for x in row:
                cnt[x["o"]] = cnt.get(x["o"], 0) + 1
            phases.append(cnt)
        complete = len(res) == len(items)
        tol = brk = None
        if complete:
            tol = round(100 * sum((rates[i + 1] - rates[i]) * (acc[i] + acc[i + 1]) / 2 for i in range(len(rates) - 1)), 1)
            brk = 1.0
            for i in range(1, len(rates)):
                if acc[i] < 0.5:
                    a0, a1 = acc[i - 1], acc[i]
                    brk = rates[i - 1] + (rates[i] - rates[i - 1]) * ((a0 - 0.5) / (a0 - a1) if a0 != a1 else 0)
                    break
            brk = round(brk, 3)
        vals = list(res.values())
        configs.append({"id": cdir.name, "model": m, "name": NAMES.get(m, m), "effort": e, "ran": ran, "graded": len(res),
                        "total": len(items), "complete": complete, "acc": acc, "phases": phases, "tolerance": tol,
                        "breaks": brk, "secs": round(sum(x["s"] or 0 for x in vals) / len(vals), 1) if vals else None,
                        "tokens": round(sum(x["t"] for x in vals) / len(vals)) if vals else None, "results": res})
    configs.sort(key=lambda c: (list(NAMES).index(c["model"]) if c["model"] in NAMES else 9, EFFORTS.index(c["effort"])))
    out = {"built": time.strftime("%Y-%m-%d %H:%M"), "rates": rates, "questions": list(qs.values()),
           "efforts": EFFORTS, "models": NAMES, "configs": configs}
    (ROOT / "site/data.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return out


if __name__ == "__main__":
    o = build()
    for c in o["configs"]:
        print(c["id"], c["graded"], "/", c["ran"], c["tolerance"], c["breaks"])
