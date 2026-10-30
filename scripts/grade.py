"""Grade GarbleBench responses blind, with Codex Luna (subscription) judges in batches.

Loops until every finished response has a grade; safe to run while run.py is still going.
Grades: results/grades/<config>__<item>.json  {"correct": bool, "behavior": str, "note": str}
"""
import argparse, asyncio, hashlib, json, os, random, re, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, GR = ROOT / "results/raw", ROOT / "results/grades"
CODEX_HOME, AGENT_HOME, WORK = "/tmp/gb-codex-home", "/tmp/gb-home", Path("/tmp/gb-grade")
BEHAVIORS = {"answered", "confirmed", "guessed", "lost"}

RUBRIC = """You are grading responses for a typo-tolerance benchmark. A user question was corrupted with typos,
dropped letters, stray characters and missing punctuation, then sent to an AI. For each record you get the
ORIGINAL question, the accepted ANSWER, the GARBLED text the AI saw, and the AI's RESPONSE.

For each record decide:
1. "correct" (true/false): true only if the response's main answer is the accepted answer to the ORIGINAL
   question. Equivalent forms count (6 = six, CO2 = carbon dioxide, Everest = Mount Everest, ~300,000 km/s =
   299,792 km/s). False if it answers a different question, gives a wrong answer, only asks for
   clarification, or lists the right answer as one of several guesses without committing to it. No partial credit.
2. "behavior", exactly one of:
   - "answered": commits to an interpretation and answers it, with no request to confirm (noting a typo in
     passing is still "answered").
   - "confirmed": answers an interpretation AND explicitly asks the user to confirm it ("did you mean...?") or
     says what it would answer if they meant something else.
   - "guessed": gives no committed answer, but names at least one specific guess at what the question was
     and asks the user which they meant.
   - "lost": no answer and no specific guess at the meaning: says it can't understand, calls it garbled or
     random, or just asks the user to rephrase.
3. "note": at most 8 words, e.g. what question it thought was asked.

Return ONLY a JSON array, one object per record, in the same order: {"k": "<key>", "correct": bool, "behavior": "...", "note": "..."}
Records:
"""


def key(cfg, item):
    return hashlib.sha1(f"{cfg}|{item}".encode()).hexdigest()[:10]


def pending(items):
    out = []
    for f in RAW.glob("*/*.json"):
        cfg, iid = f.parent.name, f.stem
        g = GR / f"{cfg}__{iid}.json"
        if g.exists():
            continue
        r = json.loads(f.read_text())
        if not r.get("response"):
            g.write_text(json.dumps({"correct": False, "behavior": "error", "note": (r.get("error") or "")[:80]}))
            continue
        out.append((cfg, iid, r["response"]))
    return out


def extract(text):
    final = ""
    for line in text.splitlines():
        if line.startswith("{"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            it = d.get("item") or {}
            if d.get("type") == "item.completed" and it.get("type") == "agent_message":
                final = it.get("text", "")
    m = re.search(r"\[.*\]", final, re.S)
    return json.loads(m.group(0)) if m else None


async def judge(batch, items, idx):
    recs, kmap = [], {}
    for cfg, iid, resp in batch:
        it = items[iid]
        k = key(cfg, iid)
        kmap[k] = (cfg, iid)
        recs.append({"key": k, "ORIGINAL": it["question"], "ANSWER": it["answer"], "GARBLED": it["prompt"],
                     "RESPONSE": resp[:1800]})
    prompt = RUBRIC + json.dumps(recs, ensure_ascii=False, indent=0)
    cwd = WORK / f"b{idx}"
    cwd.mkdir(parents=True, exist_ok=True)
    env = {"PATH": os.environ["PATH"], "HOME": AGENT_HOME, "CODEX_HOME": CODEX_HOME, "LANG": "en_US.UTF-8"}
    argv = ["codex", "exec", "-m", "gpt-6-luna", "-c", 'model_reasoning_effort="medium"', "-c", 'web_search="disabled"',
            *[x for f in ("shell_tool", "unified_exec", "plugins", "apps", "memories", "image_generation") for x in ("--disable", f)],
            "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", "--ephemeral", "--json", "-"]
    proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(prompt.encode()), 900)
    except asyncio.TimeoutError:
        proc.kill()
        return 0
    try:
        res = extract(out.decode(errors="replace")) or []
    except ValueError:
        res = []
    n = 0
    for g in res:
        if not isinstance(g, dict) or g.get("k") not in kmap or g.get("behavior") not in BEHAVIORS:
            continue
        cfg, iid = kmap[g["k"]]
        (GR / f"{cfg}__{iid}.json").write_text(json.dumps(
            {"correct": bool(g.get("correct")), "behavior": g["behavior"], "note": str(g.get("note", ""))[:120]}))
        n += 1
    return n


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    items = {it["id"]: it for it in json.loads((ROOT / "data/items.json").read_text())["items"]}
    GR.mkdir(parents=True, exist_ok=True)
    idx = 0
    while True:
        todo = pending(items)
        random.shuffle(todo)  # mixes models and levels inside each blind batch
        if not todo:
            if a.once or (ROOT / "results/RUN_DONE").exists():
                print("graded everything", flush=True)
                return
            await asyncio.sleep(60)
            continue
        if len(todo) < a.batch and not (ROOT / "results/RUN_DONE").exists():
            await asyncio.sleep(60)  # wait for a full batch
            todo = pending(items)
            random.shuffle(todo)
        batches = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
        sem = asyncio.Semaphore(a.concurrency)

        async def go(b):
            nonlocal idx
            async with sem:
                idx += 1
                n = await judge(b, items, idx)
                print(f"{time.strftime('%H:%M:%S')} graded {n}/{len(b)}", flush=True)

        await asyncio.gather(*[go(b) for b in batches])
        if a.once:
            return


if __name__ == "__main__":
    asyncio.run(main())
