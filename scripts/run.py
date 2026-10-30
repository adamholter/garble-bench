"""Run GarbleBench prompts through the Codex CLI (subscription), many in parallel.

Each prompt is one fresh `codex exec` with tools off, in an empty scratch folder and an isolated
CODEX_HOME, so the model sees only the garbled text. Results: results/raw/<config>/<item>.json.
Resume-safe: finished items are skipped.
"""
import argparse, asyncio, json, os, re, signal, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results/raw"
CODEX_HOME, AGENT_HOME, WORK = "/tmp/gb-codex-home", "/tmp/gb-home", Path("/tmp/gb-work")
MODELS = {"sol": "gpt-6.1-sol", "terra": "gpt-6.1-terra", "astra": "gpt-6-astra", "luna": "gpt-6-luna",
          "argon": "gemini-4-argon", "flash": "gemini-3.8-flash"}  # last two run through Antigravity (agy)
AGY = {"argon", "flash"}
# Cursor CLI: key -> (model id prefix, efforts it offers); the id is f"{prefix}-{effort}"
CURSOR = {"grok": ("grok-4.7", ["low", "medium", "high", "xhigh"])}
MODELS.update({k: v[0] for k, v in CURSOR.items()})
CURSOR_HOME = Path("/private/tmp/gb-cursor-home")
AGY_EFFORTS = {"low", "medium", "high"}
AGY_HOMES = Path("/private/tmp/gb-agy-homes")
AGY_TOOLS = json.loads((ROOT / "scripts/agy_tools.json").read_text())
AGY_LINKS = ["antigravity-cli/antigravity-oauth-token", "antigravity-cli/installation_id", "oauth_creds.json",
             "google_accounts.json", "installation_id"]
EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"]
NO_ULTRA = {"luna"}
CAP_RE = re.compile(r"usage limit|rate limit|429|too many requests|quota|at capacity|overloaded|503", re.I)


def configs(models, efforts):
    return [(f"{m}-{e}", MODELS[m], e) for e in efforts for m in models if not (e == "ultra" and m in NO_ULTRA) and not (m in AGY and e not in AGY_EFFORTS) and not (m in CURSOR and e not in CURSOR[m][1])]


def agy_home(tag):
    # fresh HOME keeps Adam's ~/.gemini skills and memories out; ~/Library link avoids a Keychain dialog
    home = AGY_HOMES / tag
    (home / ".gemini/antigravity-cli").mkdir(parents=True, exist_ok=True)
    for rel, src in [("Library", Path.home() / "Library")] + [(f".gemini/{f}", Path.home() / ".gemini" / f) for f in AGY_LINKS]:
        if src.exists() and not (home / rel).is_symlink():
            os.symlink(src, home / rel)
    # Codex runs have tools switched off; agy can't drop tools, so it gets the same state through global rules,
    # and a deny list blocks any call that slips through
    (home / ".gemini/GEMINI.md").write_text(
        "No tools are available in this session. Do not call any tools. Reply to the user's message directly.\n")
    return home


def drop_links(home):
    for rel in ["Library"] + [f".gemini/{f}" for f in AGY_LINKS]:
        if (home / rel).is_symlink():
            (home / rel).unlink()


def parse_agy(text):
    final, usage, err, tools = "", {}, "", []
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        su = d.get("step_update") or {}
        if su.get("step_type") == "tool" and su.get("state") == "DONE":
            tools.append(su.get("tool_name"))
        r = d.get("result")
        if d.get("event") == "result" and isinstance(r, dict):
            u = r.get("usage") or {}
            usage = {"input_tokens": u.get("input_tokens"), "output_tokens": (u.get("output_tokens") or 0) + (u.get("thinking_tokens") or 0),
                     "reasoning_output_tokens": u.get("thinking_tokens")}
            if r.get("denied_actions"):
                tools += ["denied:" + str(a.get("action", a))[:40] for a in r["denied_actions"]]
            if r.get("status") == "SUCCESS":
                final = r.get("response") or ""
            else:
                err = json.dumps(r)[:800]
    return final, usage, err, tools


def parse(text):
    final, usage, err, tools = "", {}, "", []
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        it = d.get("item") or {}
        if d.get("type") == "item.completed":
            if it.get("type") == "agent_message":
                final = it.get("text", "")
            elif it.get("type") == "mcp_tool_call":
                tools.append(f"mcp:{it.get('server')}/{it.get('tool')}")
            elif it.get("type") not in ("reasoning", "error"):
                tools.append(it.get("type"))
        elif d.get("type") == "turn.completed":
            usage = d.get("usage") or {}
        elif d.get("type") in ("error", "turn.failed"):
            err = json.dumps(d)[:800]
    return final, usage, err, tools


def reap(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def run_one(cfg, model, effort, item, timeout):
    cwd = WORK / f"{cfg}__{item['id']}"
    cwd.mkdir(parents=True, exist_ok=True)
    if any(model == v[0] for v in CURSOR.values()):
        return await run_cursor(cfg, model, effort, item, timeout, cwd)
    if model.startswith("gemini"):
        return await run_agy(cfg, model, effort, item, timeout, cwd)
    env = {"PATH": os.environ["PATH"], "HOME": AGENT_HOME, "CODEX_HOME": CODEX_HOME, "LANG": "en_US.UTF-8"}
    argv = ["codex", "exec", "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-c", 'web_search="disabled"',
            *[x for f in ("shell_tool", "unified_exec", "plugins", "apps", "memories", "image_generation") for x in ("--disable", f)],
            "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", "--ephemeral", "--json", "--", item["prompt"]]
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                start_new_session=True)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        reap(proc)
    except asyncio.TimeoutError:
        reap(proc)
        await proc.wait()
        return {"error": "timeout", "seconds": round(time.time() - t0, 1)}
    final, usage, err, tools = parse(out.decode(errors="replace"))
    return {"response": final, "usage": usage, "error": "" if final else (err or out.decode(errors="replace")[-800:]),
            "tools": tools, "seconds": round(time.time() - t0, 1)}


async def run_agy(cfg, model, effort, item, timeout, cwd):
    home = agy_home(f"{cfg}__{item['id']}")
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "LANG": "en_US.UTF-8"}
    argv = [str(Path.home() / ".local/bin/agy"), "-p", item["prompt"], "--model", f"{model}-{effort}", "--effort", effort,
            "--dangerously-skip-permissions", "--disable-slash-commands", "--output-format", "stream-json",
            "--print-timeout", f"{timeout - 30}s", "--settings", json.dumps({"permissions": {"deny": AGY_TOOLS}})]
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                start_new_session=True)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        reap(proc)
    except asyncio.TimeoutError:
        reap(proc)
        await proc.wait()
        drop_links(home)
        return {"error": "timeout", "seconds": round(time.time() - t0, 1)}
    drop_links(home)
    final, usage, err, tools = parse_agy(out.decode(errors="replace"))
    return {"response": final, "usage": usage, "error": "" if final else (err or out.decode(errors="replace")[-800:]),
            "tools": tools, "seconds": round(time.time() - t0, 1)}


def parse_cursor(text):
    final, usage, err, tools = "", {}, "", []
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "tool_call" and d.get("subtype") == "started":
            tools.append(next(iter(d.get("tool_call") or {"tool": 0})))
        if d.get("type") == "result":
            u = d.get("usage") or {}
            usage = {"input_tokens": u.get("inputTokens"), "cached_input_tokens": u.get("cacheReadTokens"),
                     "output_tokens": u.get("outputTokens")}
            if d.get("is_error") or d.get("subtype") != "success":
                err = json.dumps(d)[:800]
            else:
                final = d.get("result") or ""
    return final, usage, err, tools


async def run_cursor(cfg, model, effort, item, timeout, cwd):
    # a home without Adam's Cursor rules, skills and MCP servers; sign-in is in the keychain
    CURSOR_HOME.mkdir(parents=True, exist_ok=True)
    if not (CURSOR_HOME / "Library").is_symlink():
        try:
            os.symlink(Path.home() / "Library", CURSOR_HOME / "Library")
        except FileExistsError:
            pass
    env = {"PATH": os.environ["PATH"], "HOME": str(CURSOR_HOME), "LANG": "en_US.UTF-8"}
    argv = [str(Path.home() / ".local/bin/cursor-agent"), "-p", "--model", f"{model}-{effort}", "--mode", "ask",
            "--output-format", "stream-json", "--trust", "--workspace", str(cwd), item["prompt"]]
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                start_new_session=True)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        reap(proc)
    except asyncio.TimeoutError:
        reap(proc)
        await proc.wait()
        return {"error": "timeout", "seconds": round(time.time() - t0, 1)}
    final, usage, err, tools = parse_cursor(out.decode(errors="replace"))
    return {"response": final, "usage": usage, "error": "" if final else (err or out.decode(errors="replace")[-800:]),
            "tools": tools, "seconds": round(time.time() - t0, 1)}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="sol,terra,astra,luna")
    ap.add_argument("--efforts", default=",".join(EFFORTS))
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="items per config (smoke test)")
    a = ap.parse_args()
    items = json.loads((ROOT / "data/items.json").read_text())["items"]
    if a.limit:
        items = items[: a.limit]
    for d in (CODEX_HOME, AGENT_HOME):
        Path(d).mkdir(parents=True, exist_ok=True)
    if not (Path(CODEX_HOME) / "auth.json").exists():
        os.symlink(Path.home() / ".codex/auth.json", Path(CODEX_HOME) / "auth.json")
    # effort tiers in order so whole configs complete first; within a tier, interleave models
    jobs = [(c, it) for c in configs(a.models.split(","), a.efforts.split(",")) for it in items
            if not (RAW / c[0] / f"{it['id']}.json").exists()]
    tier = {e: i for i, e in enumerate(EFFORTS)}
    jobs.sort(key=lambda j: (tier[j[0][2]], items.index(j[1]), j[0][0]))
    print(f"{len(jobs)} jobs, concurrency {a.concurrency}", flush=True)
    q = asyncio.Queue()
    for j in jobs:
        q.put_nowait(j)
    done = [0]
    pause = {"until": 0.0}

    async def worker():
        while not q.empty():
            (cfg, model, effort), item = await q.get()
            if (RAW / cfg / f"{item['id']}.json").exists():
                continue
            while time.time() < pause["until"]:
                await asyncio.sleep(5)
            timeout = 600 if effort in ("low", "medium") else 2400
            r = await run_one(cfg, model, effort, item, timeout)
            if not r.get("response") and CAP_RE.search(r.get("error", "")):
                print(f"[cap] {cfg} {item['id']}: {r['error'][:200]}", flush=True)
                pause["until"] = time.time() + 120
                q.put_nowait(((cfg, model, effort), item))
                continue
            if not r.get("response"):
                r.setdefault("attempts", 1)
                prev = RAW / cfg / f"{item['id']}.err"
                n = int(prev.read_text()) + 1 if prev.exists() else 1
                prev.parent.mkdir(parents=True, exist_ok=True)
                prev.write_text(str(n))
                print(f"[err {n}] {cfg} {item['id']}: {r.get('error','')[:200]}", flush=True)
                if n < 3:
                    q.put_nowait(((cfg, model, effort), item))
                    continue
            r.update({"config": cfg, "model": model, "effort": effort, "item": item["id"]})
            p = RAW / cfg / f"{item['id']}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(r, indent=1))
            done[0] += 1
            if done[0] % 25 == 0:
                print(f"{time.strftime('%H:%M:%S')} done {done[0]}/{len(jobs)} last {cfg} {r['seconds']}s", flush=True)

    await asyncio.gather(*[worker() for _ in range(a.concurrency)])
    print("all done", flush=True)
    (ROOT / f"results/RUN_DONE_{a.models.replace(',', '_')}").touch()


if __name__ == "__main__":
    asyncio.run(main())
