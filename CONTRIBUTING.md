# Contributing runs

The most useful thing you can add is a model at a reasoning effort that is not on the site yet. A run is 288 short prompts, one model, one effort, one file.

## Before you start

1. Check the site for what is already there, and `submissions/` for pending pull requests.
2. Pick **one model and one effort** per run. Run more efforts as separate runs.
3. Make sure the CLI is signed in and works with one normal message.

## Run it

```bash
python3 garble.py run --harness <h> --model <id> --effort <e> --contributor <github-handle>
```

| Harness | Example | Notes |
|---|---|---|
| `cursor` | `--model grok-4.7 --effort high` | Cursor CLI in ask mode. Sent as `<model>-<effort>`, so use the id Cursor lists (`cursor-agent --list-models`). |
| `codex` | `--model gpt-6.1-sol --effort xhigh` | Uses your Codex sign-in in an isolated, tool-free home. |
| `agy` | `--model gemini-4-argon --effort high` | Antigravity. Cannot drop tools, so a rules file says no tools and a deny list blocks them. |
| `muse` | `--model muse-wonder-1.0-contributor --effort high` | Muse Code. Prefer contributor-mode ids if your plan has them: it is cheaper. |
| `openrouter` | `--model moonshotai/kimi-k3.1 --effort high` | Needs `OPENROUTER_API_KEY`. Costs money (small: a few dollars at most). |
| `cmd` | `--cmd 'mycli -p {prompt}'` | Any other tool; its stdout is the reply. You are responsible for making it tool-free. |

Use `--effort default` if the model has no effort setting.

### Look after your machine and your quota

- `--concurrency` defaults to 4. Eight is plenty; more only helps if the service is slow, and every CLI is a process that uses memory. The runner kills each CLI's whole process group when it finishes, because some (Cursor's) leave a worker behind per call. On macOS it also pauses if free memory drops under 20%.
- Smoke-test first: add `--limit 3` to send three prompts and see the replies before committing a full run.
- If you hit your usage limit it waits five minutes and retries. Press Ctrl-C any time and rerun the same command; finished prompts are kept in `.garble-work/`.
- Each prompt is one short message but CLIs add their own system prompt, so cost is mostly fixed overhead per call. High efforts also think longer. Do the cheap efforts first.

## Submit

```bash
python3 garble.py verify submissions/<file>.json
```

Fork, commit only that file, open a pull request. `verify` runs on the pull request too. It checks that all 288 prompts have replies, the dataset matches, and **no tool calls** were made. If it reports tool calls, those runs are not valid; rerun them.

## Rules that keep the numbers comparable

- Fresh session per prompt, nothing else in the context. The runner does this.
- No tools, web search, memory, skills or personal rules files. Do not edit the prompts.
- Do not hand-edit replies. Replies that errored stay empty and count as no reply.
- Say what you used in `--note` if anything is unusual (an unofficial endpoint, a mode that could not be changed).

## Grading

You do not grade. Submissions are graded blind by one grader (GPT-6 Luna, shuffled batches of 40, no partial credit) so every model is judged the same way. `python3 garble.py preview` gives you a rough number straight away; it only checks that the expected answer appears in the reply.

## Maintainer notes

```bash
python3 scripts/ingest.py submissions/<file>.json   # -> results/raw/<name>/
python3 scripts/grade.py --once                     # blind grading with Codex
python3 scripts/build_site.py
```

Add new model names and colours to `scripts/build_site.py` (`NAMES`) and `site/app.js`. Publish a model only when its run is complete.
