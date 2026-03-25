# autoresearch-anything

Set up an autonomous AI improvement loop for **any** project. Inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch).

Run the setup script, answer a few questions about your project, and it generates a `setup.md` that tells your AI coding agent exactly how to run an overnight improvement loop.

## Quick start

```bash
npx autoresearch-anything
```

Or clone and run directly:

```bash
git clone https://github.com/zkarimi22/autoresearch-anything.git
cd my-cool-project                              # your project, not the cloned repo
node ../autoresearch-anything/init.js           # adjust the path to where you cloned it
```

## What it does

The script asks you about your project:

- What file(s) should the agent edit?
- What metric are you optimizing?
- How to run the eval and extract the score?
- Any constraints or secondary metrics?

Then it generates:

- **setup.md** — Complete instructions for your AI agent. Which files to edit, how to run eval, how to log results, and to never stop.
- **eval.js** — A starter template for your evaluation script (optional).

## How to use the output

Once you have `setup.md` (and your eval script is ready):

1. Open Claude Code (or any AI coding agent) in your project directory
2. Tell it: **"Read setup.md and kick off a new experiment. Do the setup first."**
3. Walk away

The agent will loop: edit code, commit, run eval, keep improvements, discard failures. Each experiment takes a few minutes — roughly 12/hour, 100 overnight.

## The pattern

```
LOOP FOREVER:
  1. Edit the code
  2. git commit
  3. Run eval → get a score
  4. Score improved? Keep. Score worse? git reset.
  5. Log results. Repeat.
```

This works for anything measurable: system prompts, API performance, landing pages, test suites, config tuning, SQL queries.

## Example session

```
$ npx autoresearch-anything

╔═══════════════════════════════════════════╗
║        autoresearch-anything              ║
║   Autonomous AI improvement loop setup    ║
╚═══════════════════════════════════════════╝

Briefly describe your project: AI agent that generates React components
What file(s) should the agent edit? (comma-separated): system-prompt.md
What's your metric called? (score): pass_rate
Should the metric go up or down? (up): up
What command runs your eval and prints the score? (node eval.js): node eval.js
What does the score line look like in stdout? (pass_rate: 85.3): pass_rate: 85.3
Track a secondary constraint? [y/N]: y
What's the secondary metric called? (cost): api_cost
How does the secondary metric appear in stdout? (api_cost: 1.23): api_cost: 0.12
Max time per experiment in minutes? (10): 10
Prerequisites to verify before starting? (none): npm install
Other files the agent should read for context? (README.md): README.md, pipeline.js
Files the agent must NOT modify? (eval.js): eval.js, test_cases/
Any additional rules or constraints? (or 'none'): none
Generate a starter eval.js template? [Y/n]: y

Created: setup.md
Created: eval.js (starter template — fill in your evaluation logic)

Done! Next steps:

  1. Fill in eval.js with your actual evaluation logic
  2. Open your AI coding agent (Claude Code, Codex, etc.) in this directory
  3. Tell it: "Read setup.md and kick off a new experiment. Do the setup first."
  4. Walk away
```

## License

MIT
