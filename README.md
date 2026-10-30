# GarbleBench

How well do AI models understand questions full of typos?

24 plain questions, each corrupted at 12 rates from clean to fully mangled: neighbouring-key typos, dropped letters, stray characters, swapped pairs, lost punctuation. Every prompt goes to a fresh agent session with nothing else in it. Models are scored on how much corruption they read through (tolerance) and where they break. Idea by [Matthew Miskiewicz](https://x.com/MattOfMisk).

**Results and replies:** https://garble-bench.adamholter.chatgpt.site

## Run a model and add it

You do not need to be a developer. If you have a Cursor, Codex, Antigravity or Muse Code plan with models that are not on the site yet, one command runs the whole benchmark on your own usage and writes one file you can send back.

```bash
git clone https://github.com/adamholter/garble-bench && cd garble-bench
python3 garble.py harnesses            # what is installed
python3 garble.py run --harness cursor --model grok-4.7 --effort high --contributor YOUR_GITHUB_HANDLE
```

Needs Python 3.9+ and the CLI you want to use, already signed in. No packages to install. It sends 288 prompts, four at a time by default, resumes if you stop it, waits when you hit a usage limit, and finishes by writing `submissions/<model>-<effort>__<you>.json`. Then:

```bash
python3 garble.py preview submissions/<file>.json   # rough scores, instantly
python3 garble.py verify  submissions/<file>.json
```

Fork the repo, add that one file and open a pull request. A check runs `verify` for you. The maintainer grades it blind and adds it to the site, credited to you.

Details, harness examples and tips for saving usage: [CONTRIBUTING.md](CONTRIBUTING.md).

## How it works

- `data/items.json`: the 288 prompts (24 questions x 12 rates) with answers. The corruption is nested: the 40% version keeps every error from the 30% version, so a curve shows where reading gives out, not the luck of the draw. `scripts/build_dataset.py` makes it, seeded.
- `garble.py`: contributor runner and checker.
- `scripts/run.py`, `scripts/grade.py`: the maintainer's batch runner and the blind grader (GPT-6 Luna judges shuffled batches of 40 replies against the original question and answer; no partial credit).
- `scripts/ingest.py`, `scripts/build_site.py`: turn a submission into graded results and the site data. `site/` is the static page. To view it, run `python3 scripts/build_site.py && python3 -m http.server -d site`.
- `results/`: every reply and grade behind the published numbers.

**Scoring.** Tolerance is the area under the accuracy curve from 0 to 100% corruption. Breaks at is the corruption rate where accuracy first falls below half. Behaviour is one of answered, confirmed (answered and asked "did you mean"), guessed (offered readings, no answer) or lost (asked to rephrase).

**Tool-free rule.** Models must answer from the text alone: no shell, web search, memory or personal rules files. The built-in harnesses switch these off. An early Gemini pass without that let a model write Python to unscramble keyboard layouts; it was thrown out. `verify` rejects any submission with tool calls.
