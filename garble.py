#!/usr/bin/env python3
"""GarbleBench contributor CLI. Standard library only.

    python3 garble.py harnesses
    python3 garble.py run --harness cursor --model grok-4.7 --effort high --contributor yourhandle
    python3 garble.py preview submissions/<file>.json
    python3 garble.py verify  submissions/<file>.json

`run` sends all 288 prompts (24 questions x 12 corruption rates) to one model at one reasoning effort,
resumes where it stopped, and writes submissions/<name>.json when every prompt has a reply.
Open a pull request with that one file; the maintainer grades it and adds it to the site.
"""
import argparse, asyncio, hashlib, json, os, platform, re, shlex, signal, shutil, subprocess, sys, time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ITEMS = json.loads((ROOT / "data/items.json").read_text())["items"]
DATASET_SHA = hashlib.sha256((ROOT / "data/items.json").read_bytes()).hexdigest()[:12]
WORK = ROOT / ".garble-work"          # per-run scratch and progress, git-ignored
SUB = ROOT / "submissions"
MAC = platform.system() == "Darwin"
CAP_RE = re.compile(r"usage limit|rate limit|429|too many requests|quota|at capacity|overloaded|503", re.I)
NOTE = ("Each prompt must reach the model alone, in a fresh session, with no tools, no web search, no memory and "
        "no personal rules files. If your CLI cannot turn tools off, say so with --note.")


# ---------------------------------------------------------------- harnesses
# Each harness: build(model, effort, prompt, ctx) -> (argv, env, cwd-relative flags) and parse(text) -> (final, usage, err, tools)

def jlines(text):
    for line in text.splitlines():
        if line.startswith("{"):
            try:
                yield json.loads(line)
            except ValueError:
                pass


def parse_codex(text):
    final, usage, err, tools = "", {}, "", []
    for d in jlines(text):
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


def parse_cursor(text):
    final, usage, err, tools = "", {}, "", []
    for d in jlines(text):
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


def parse_agy(text):
    final, usage, err, tools = "", {}, "", []
    for d in jlines(text):
        su = d.get("step_update") or {}
        if su.get("step_type") == "tool" and su.get("state") == "DONE":
            tools.append(su.get("tool_name"))
        r = d.get("result")
        if d.get("event") == "result" and isinstance(r, dict):
            u = r.get("usage") or {}
            usage = {"input_tokens": u.get("input_tokens"),
                     "output_tokens": (u.get("output_tokens") or 0) + (u.get("thinking_tokens") or 0)}
            if r.get("denied_actions"):
                tools += ["denied:" + str(a.get("action", a))[:40] for a in r["denied_actions"]]
            if r.get("status") == "SUCCESS":
                final = r.get("response") or ""
            else:
                err = json.dumps(r)[:800]
    return final, usage, err, tools


def parse_muse(text):
    final, err, tools = "", "", []
    for d in jlines(text):
        if d.get("payload_type") == "run.terminal.completed":
            final = (d.get("payload") or {}).get("text") or ""
        elif d.get("payload_type") == "run.terminal.failed":
            err = json.dumps(d.get("payload"))[:800]
    return final, {}, err, tools


def parse_plain(text):
    return text.strip(), {}, "", []


def link_mac_library(home):
    # macOS keeps CLI sign-ins in the login keychain under ~/Library; a fresh HOME needs that link
    if MAC and not (home / "Library").exists():
        os.symlink(Path.home() / "Library", home / "Library")


def b_codex(model, effort, prompt, ctx):
    home = Path(ctx["scratch"]) / "codex-home"
    home.mkdir(parents=True, exist_ok=True)
    real = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    for f in ("auth.json", "config.toml"):
        if f == "auth.json" and (real / f).exists() and not (home / f).exists():
            os.symlink(real / f, home / f)
    argv = ["codex", "exec", "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-c", 'web_search="disabled"',
            *[x for f in ("shell_tool", "unified_exec", "plugins", "apps", "memories", "image_generation")
              for x in ("--disable", f)],
            "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", "--ephemeral", "--json", "--", prompt]
    return argv, {"CODEX_HOME": str(home)}


def b_cursor(model, effort, prompt, ctx):
    home = Path(ctx["scratch"]) / "cursor-home"
    home.mkdir(parents=True, exist_ok=True)
    link_mac_library(home)
    argv = ["cursor-agent", "-p", "--model", f"{model}-{effort}" if effort != "default" else model, "--mode", "ask",
            "--output-format", "stream-json", "--trust", "--workspace", ctx["cwd"], prompt]
    return argv, {"HOME": str(home)} if MAC else {}


def b_agy(model, effort, prompt, ctx):
    home = Path(ctx["scratch"]) / "agy-home" / ctx["tag"]
    (home / ".gemini/antigravity-cli").mkdir(parents=True, exist_ok=True)
    link_mac_library(home)
    for rel in ("antigravity-cli/antigravity-oauth-token", "antigravity-cli/installation_id", "oauth_creds.json",
                "google_accounts.json", "installation_id"):
        src, dst = Path.home() / ".gemini" / rel, home / ".gemini" / rel
        if src.exists() and not dst.exists():
            os.symlink(src, dst)
    (home / ".gemini/GEMINI.md").write_text(
        "No tools are available in this session. Do not call any tools. Reply to the user's message directly.\n")
    deny = json.loads((ROOT / "scripts/agy_tools.json").read_text())
    argv = ["agy", "-p", prompt, "--model", f"{model}-{effort}", "--effort", effort, "--dangerously-skip-permissions",
            "--disable-slash-commands", "--output-format", "stream-json", "--print-timeout", f"{ctx['timeout'] - 30}s",
            "--settings", json.dumps({"permissions": {"deny": deny}})]
    return argv, {"HOME": str(home)}


def b_muse(model, effort, prompt, ctx):
    home = Path(ctx["scratch"]) / "muse-home" / ctx["tag"]
    (home / ".config/muse").mkdir(parents=True, exist_ok=True)
    link_mac_library(home)
    auth = Path.home() / ".config/muse/auth.json"
    if auth.exists() and not (home / ".config/muse/auth.json").exists():
        os.symlink(auth, home / ".config/muse/auth.json")
    argv = ["muse", "exec", "--json", "--preset", "empty", "--model", model, "--yolo", "--no-foreign-personal-context"]
    if effort != "default":
        argv += ["--reasoning-effort", effort]
    return argv + [prompt], {"HOME": str(home)}


HARNESSES = {
    "codex":  {"build": b_codex,  "parse": parse_codex,  "desc": "OpenAI Codex CLI (ChatGPT subscription). --model gpt-6.1-sol --effort high",
               "efforts": "low medium high xhigh max ultra", "bin": "codex"},
    "cursor": {"build": b_cursor, "parse": parse_cursor, "desc": "Cursor CLI, ask mode (Cursor plan). --model grok-4.7 --effort high  (id sent as <model>-<effort>)",
               "efforts": "low medium high xhigh (model-dependent)", "bin": "cursor-agent"},
    "agy":    {"build": b_agy,    "parse": parse_agy,    "desc": "Google Antigravity CLI. --model gemini-4-argon --effort high",
               "efforts": "low medium high", "bin": "agy"},
    "muse":   {"build": b_muse,   "parse": parse_muse,   "desc": "Meta Muse Code CLI. --model muse-wonder-1.0-contributor --effort high",
               "efforts": "model-dependent, or 'default'", "bin": "muse"},
    "openrouter": {"desc": "OpenRouter API (needs OPENROUTER_API_KEY, costs money). --model moonshotai/kimi-k3.1 --effort high",
                   "efforts": "low medium high, or 'default'", "bin": None},
    "cmd":    {"desc": "Any command: --cmd 'mytool --model x -p {prompt}'. Its stdout is the reply. Placeholders {prompt} {model} {effort}",
               "efforts": "whatever you label it", "bin": None},
}


def openrouter_call(model, effort, prompt, timeout):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return {"error": "OPENROUTER_API_KEY not set"}
    body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if effort != "default":
        body["reasoning"] = {"effort": effort}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:400]}
    u = d.get("usage") or {}
    msg = ((d.get("choices") or [{}])[0].get("message") or {})
    return {"response": msg.get("content") or "", "error": "" if msg.get("content") else json.dumps(d)[:400],
            "usage": {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens"),
                      "cost": u.get("cost")}, "tools": []}


def reap(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def one(args, item, scratch):
    h = HARNESSES[args.harness]
    t0 = time.time()
    if args.harness == "openrouter":
        r = await asyncio.get_running_loop().run_in_executor(
            None, openrouter_call, args.model, args.effort, item["prompt"], args.timeout)
        r["seconds"] = round(time.time() - t0, 1)
        return r
    cwd = scratch / "cwd" / item["id"]
    cwd.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if args.harness == "cmd":
        argv = [a.replace("{prompt}", item["prompt"]).replace("{model}", args.model).replace("{effort}", args.effort)
                for a in shlex.split(args.cmd)]
        parse = parse_plain
    else:
        ctx = {"scratch": str(scratch), "cwd": str(cwd), "tag": item["id"], "timeout": args.timeout}
        argv, extra = h["build"](args.model, args.effort, item["prompt"], ctx)
        env.update(extra)
        parse = h["parse"]
    try:
        # own process group, so a CLI's leftover worker processes die with it (cursor-agent leaves one per call)
        proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                    start_new_session=True)
    except FileNotFoundError:
        return {"error": f"command not found: {argv[0]}", "seconds": 0}
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), args.timeout)
        reap(proc)
    except asyncio.TimeoutError:
        reap(proc)
        await proc.wait()
        return {"error": "timeout", "seconds": round(time.time() - t0, 1)}
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    final, usage, err, tools = parse(out.decode(errors="replace"))
    return {"response": final, "usage": usage, "tools": tools, "seconds": round(time.time() - t0, 1),
            "error": "" if final else (err or out.decode(errors="replace")[-400:])}


# ---------------------------------------------------------------- commands

def slug(s):
    return re.sub(r"[^a-z0-9.]+", "-", s.lower()).strip("-")


def cmd_harnesses(_):
    for k, h in HARNESSES.items():
        have = "" if not h["bin"] else ("  [installed]" if shutil.which(h["bin"]) else "  [not on PATH]")
        print(f"{k:11} {h['desc']}{have}\n{'':11} efforts: {h['efforts']}")


def mem_free_pct():
    if not MAC:
        return None
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"free percentage: (\d+)%", out)
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


async def cmd_run_async(a):
    if a.harness not in HARNESSES:
        sys.exit(f"unknown harness {a.harness}; try `python3 garble.py harnesses`")
    if a.harness == "cmd" and not a.cmd:
        sys.exit("--cmd is required with --harness cmd")
    if a.harness not in ("openrouter", "cmd") and not shutil.which(HARNESSES[a.harness]["bin"]):
        sys.exit(f"`{HARNESSES[a.harness]['bin']}` is not on your PATH")
    name = a.name or slug(f"{a.model.split('/')[-1]}-{a.effort}")
    scratch = WORK / name
    prog = scratch / "replies"
    prog.mkdir(parents=True, exist_ok=True)
    items = ITEMS[: a.limit] if a.limit else ITEMS
    todo = [it for it in items if not (prog / f"{it['id']}.json").exists()]
    print(f"{name}: {len(items) - len(todo)}/{len(items)} done, {len(todo)} to run, {a.concurrency} at a time", flush=True)
    print(NOTE, flush=True)
    q = asyncio.Queue()
    for it in todo:
        q.put_nowait(it)
    pause, finished, fails = [0.0], [0], {}
    stop = asyncio.Event()

    async def worker():
        while not q.empty() and not stop.is_set():
            item = q.get_nowait()
            while time.time() < pause[0]:
                await asyncio.sleep(5)
            r = await one(a, item, scratch)
            if not r.get("response") and CAP_RE.search(r.get("error", "")):
                print(f"[limit] {item['id']}: {r['error'][:160]}\n  waiting 5 min; Ctrl-C to stop (progress is saved)", flush=True)
                pause[0] = time.time() + 300
                q.put_nowait(item)
                continue
            if not r.get("response"):
                fails[item["id"]] = fails.get(item["id"], 0) + 1
                print(f"[error {fails[item['id']]}] {item['id']}: {r.get('error', '')[:160]}", flush=True)
                if fails[item["id"]] < 3:
                    q.put_nowait(item)
                    continue
            r["id"] = item["id"]
            (prog / f"{item['id']}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
            finished[0] += 1
            if finished[0] % 10 == 0:
                free = mem_free_pct()
                print(f"{time.strftime('%H:%M:%S')} {finished[0]}/{len(todo)} done"
                      + (f", free memory {free}%" if free is not None else ""), flush=True)
                if free is not None and free < 20:
                    print("memory is low: pausing 60s", flush=True)
                    pause[0] = time.time() + 60

    await asyncio.gather(*[worker() for _ in range(a.concurrency)])
    got = {p.stem: json.loads(p.read_text()) for p in prog.glob("*.json")}
    missing = [it["id"] for it in items if it["id"] not in got]
    errors = [k for k, v in got.items() if not v.get("response")]
    if missing or a.limit:
        print(f"stopped with {len(missing)} prompts missing; rerun the same command to continue"
              + (" (--limit run: not packed)" if a.limit else ""))
        return
    sub = {"schema": 1, "name": name, "harness": a.harness, "model": a.model, "effort": a.effort,
           "contributor": a.contributor, "date": time.strftime("%Y-%m-%d"), "dataset": DATASET_SHA,
           "note": a.note, "tool_use_note": NOTE, "replies": {it["id"]: got[it["id"]] for it in ITEMS}}
    SUB.mkdir(exist_ok=True)
    out = SUB / f"{name}__{slug(a.contributor)}.json"
    out.write_text(json.dumps(sub, indent=1, ensure_ascii=False))
    print(f"\nwrote {out.relative_to(ROOT)} ({len(errors)} prompts with no reply)")
    problems = verify(out)
    print("verify:", "ok" if not problems else "\n  " + "\n  ".join(problems))
    print("Next: fork the repo, add this one file, open a pull request.")


def cmd_run(a):
    asyncio.run(cmd_run_async(a))


def load_sub(path):
    return json.loads(Path(path).read_text())


def verify(path):
    p = []
    try:
        s = load_sub(path)
    except Exception as e:  # noqa: BLE001
        return [f"not valid JSON: {e}"]
    for k in ("schema", "name", "harness", "model", "effort", "contributor", "dataset", "replies"):
        if k not in s:
            p.append(f"missing field: {k}")
    if p:
        return p
    if s["dataset"] != DATASET_SHA:
        p.append(f"dataset mismatch ({s['dataset']} vs {DATASET_SHA}): rerun with the current repo")
    if s["harness"] not in HARNESSES:
        p.append(f"unknown harness {s['harness']}")
    if not re.fullmatch(r"[\w.-]{1,40}", str(s["contributor"])):
        p.append("contributor should be your GitHub handle")
    ids = {it["id"] for it in ITEMS}
    if set(s["replies"]) != ids:
        p.append(f"replies cover {len(set(s['replies']) & ids)}/{len(ids)} prompts")
    empty = [k for k, v in s["replies"].items() if not (v.get("response") or "").strip()]
    if len(empty) > 0.1 * len(ids):
        p.append(f"{len(empty)} prompts have no reply; rerun them before submitting")
    used = sorted({t for v in s["replies"].values() for t in (v.get("tools") or []) if t})
    if used:
        n = sum(1 for v in s["replies"].values() if v.get("tools"))
        p.append(f"tool calls on {n} replies ({', '.join(used[:5])}): runs must be tool-free, rerun those prompts")
    return p


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", t.lower().replace(",", "")).strip()


def cmd_preview(a):
    s = load_sub(a.file)
    by_level = {}
    for it in ITEMS:
        r = (s["replies"].get(it["id"]) or {}).get("response", "")
        ok = norm(it["answer"]) in norm(r)
        by_level.setdefault(it["level"], []).append(ok)
    rates = json.loads((ROOT / "data/items.json").read_text())["rates"]
    print(f"{s['name']}  (rough check: the expected answer appears in the reply; the real grade is blind and stricter)")
    for lv in sorted(by_level):
        v = by_level[lv]
        print(f"  {rates[lv]*100:>4.0f}% corrupted  {sum(v):>2}/{len(v)}  {'#' * round(20 * sum(v) / len(v))}")
    allv = [x for v in by_level.values() for x in v]
    print(f"  overall {sum(allv)}/{len(allv)}")


def cmd_verify(a):
    bad = 0
    for f in a.files:
        pr = verify(f)
        print(f"{f}: {'ok' if not pr else 'PROBLEMS'}")
        for x in pr:
            print("  -", x)
        bad += bool(pr)
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("harnesses", help="list supported CLIs and APIs").set_defaults(fn=cmd_harnesses)
    r = sp.add_parser("run", help="run all 288 prompts for one model + effort")
    r.add_argument("--harness", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--effort", default="default", help="reasoning effort as the CLI names it, or 'default'")
    r.add_argument("--contributor", required=True, help="your GitHub handle")
    r.add_argument("--name", help="config name, default <model>-<effort>")
    r.add_argument("--concurrency", type=int, default=4, help="parallel prompts; 8 is plenty, watch your memory")
    r.add_argument("--timeout", type=int, default=900, help="seconds per prompt")
    r.add_argument("--limit", type=int, default=0, help="only the first N prompts, as a smoke test (not packed)")
    r.add_argument("--cmd", help="command template for --harness cmd")
    r.add_argument("--note", default="", help="anything a reviewer should know (plan, mode, quirks)")
    r.set_defaults(fn=cmd_run)
    pv = sp.add_parser("preview", help="rough accuracy by corruption rate, no grader needed")
    pv.add_argument("file")
    pv.set_defaults(fn=cmd_preview)
    v = sp.add_parser("verify", help="check a submission file")
    v.add_argument("files", nargs="+")
    v.set_defaults(fn=cmd_verify)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
