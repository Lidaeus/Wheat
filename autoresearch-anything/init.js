#!/usr/bin/env node

import { createInterface } from "readline";
import { writeFileSync, existsSync } from "fs";
import { resolve } from "path";

// --- Input handling (works both interactively and with piped input) ---

const isTTY = process.stdin.isTTY;
let stdinLines = null;
let lineIndex = 0;

if (!isTTY) {
  stdinLines = await new Promise((res) => {
    let data = "";
    process.stdin.setEncoding("utf-8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => res(data.split("\n")));
  });
}

function ask(question, fallback) {
  const suffix = fallback ? ` (${fallback}): ` : ": ";
  const prompt = question + suffix;

  if (!isTTY) {
    process.stdout.write(prompt);
    const answer = (stdinLines[lineIndex++] || "").trim();
    console.log(answer || fallback || "");
    return Promise.resolve(answer || fallback || "");
  }

  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((res) => {
    rl.question(prompt, (a) => {
      rl.close();
      res(a.trim() || fallback || "");
    });
  });
}

async function askYN(question, fallback = "y") {
  const label = fallback === "y" ? "Y/n" : "y/N";
  const answer = await ask(`${question} [${label}]`, fallback);
  return answer.toLowerCase() === "y" || answer.toLowerCase() === "yes";
}

// --- Main ---

async function main() {
  console.log(`
╔═══════════════════════════════════════════╗
║        autoresearch-anything              ║
║   Autonomous AI improvement loop setup    ║
╚═══════════════════════════════════════════╝
`);
  console.log(
    "Answer a few questions about your project. This will generate a",
  );
  console.log(
    "setup.md file you can hand to Claude Code (or any AI coding agent).\n",
  );

  // --- Questions ---

  const projectDesc = await ask(
    "Briefly describe your project (one sentence)",
  );
  if (!projectDesc) {
    console.error("A project description is required. Exiting.");
    process.exit(1);
  }

  const mutableFiles = await ask(
    "What file(s) should the agent edit? (comma-separated)",
  );
  if (!mutableFiles) {
    console.error("You need at least one file. Exiting.");
    process.exit(1);
  }
  const fileList = mutableFiles.split(",").map((f) => f.trim());

  const metricName = await ask("What's your metric called?", "score");

  const metricDirection = await ask(
    "Should the metric go up or down?",
    "up",
  );
  const higherIsBetter = metricDirection.toLowerCase().startsWith("u");

  const evalCommand = await ask(
    "What command runs your eval and prints the score?",
    "node eval.js",
  );

  const scorePattern = await ask(
    `What does the score line look like in stdout?`,
    `${metricName}: 85.3`,
  );

  const hasSecondary = await askYN(
    "Track a secondary constraint? (cost, memory, bundle size, etc.)",
    "n",
  );
  let secondaryName = "";
  let secondaryGrep = "";
  if (hasSecondary) {
    secondaryName = await ask(
      "What's the secondary metric called?",
      "cost",
    );
    secondaryGrep = await ask(
      "How does the secondary metric appear in stdout?",
      `${secondaryName}: 1.23`,
    );
  }

  const timeout = await ask("Max time per experiment in minutes?", "10");
  const timeoutSeconds = parseInt(timeout) * 60;

  const prereqs = await ask(
    "Prerequisites to verify before starting? (e.g. 'npm install', 'db running')",
    "none",
  );

  const readFiles = await ask(
    "Other files the agent should read for context? (comma-separated)",
    "README.md",
  );
  const readFileList = readFiles.split(",").map((f) => f.trim());

  const noTouchFiles = await ask(
    "Files the agent must NOT modify? (comma-separated)",
    "eval.js",
  );
  const noTouchList = noTouchFiles.split(",").map((f) => f.trim());

  const extraRules = await ask(
    "Any additional rules or constraints? (or 'none')",
    "none",
  );

  const generateEval = await askYN("Generate a starter eval.js template?", "y");

  // --- Build setup.md ---

  const fileListFormatted = fileList.map((f) => `\`${f}\``).join(", ");
  const fileListBullets = fileList.map((f) => `   - \`${f}\``).join("\n");
  const readFileBullets = readFileList.map((f) => `   - \`${f}\``).join("\n");
  const noTouchBullets = noTouchList
    .map((f) => `- Do NOT modify \`${f}\`.`)
    .join("\n");
  const goalVerb = higherIsBetter ? "maximize" : "minimize";
  const compareOp = higherIsBetter ? "improved (higher)" : "improved (lower)";
  const compareRevert = higherIsBetter
    ? "equal or worse (lower or same)"
    : "equal or worse (higher or same)";

  const tsvHeader = hasSecondary
    ? `commit\t${metricName}\t${secondaryName}\tstatus\tdescription`
    : `commit\t${metricName}\tstatus\tdescription`;

  const grepMetric = `grep "^${metricName}:" run.log`;
  const grepSecondary = hasSecondary
    ? `\n   Also extract: \`grep "^${secondaryName}:" run.log\``
    : "";

  const secondaryRule = hasSecondary
    ? `\n- **${secondaryName}** is a soft constraint. Some increase is acceptable for meaningful ${metricName} gains, but it should not blow up dramatically.`
    : "";

  const extraRulesBlock =
    extraRules === "none" ? "" : `\n- ${extraRules}`;

  let prereqBlock = "";
  if (prereqs !== "none") {
    prereqBlock = `3. **Verify prerequisites**: ${prereqs}. If anything is missing, tell the human and stop.\n`;
  }

  const setupMd = `# Autonomous Improvement Loop

> ${projectDesc}

## Setup

To set up a new experiment run:

1. **Create branch**: \`git checkout -b autoloop/<tag>\` from main. Pick a tag based on today's date (e.g. \`mar9\`). The branch must not already exist.
2. **Read the codebase** for full context:
${readFileBullets}
${fileListBullets}
${prereqBlock ? prereqBlock : ""}${prereqBlock ? "4" : "3"}. **Create results.tsv** with this header row:
   \`${tsvHeader}\`
${prereqBlock ? "5" : "4"}. **Establish baseline**: Run the eval command as-is before making any changes. Log the result as the first row.
${prereqBlock ? "6" : "5"}. **Confirm and go**: Confirm setup looks good with the human, then begin the loop.

## Rules

**What you CAN do:**
- Modify ${fileListFormatted}. Everything in these files is fair game.

**What you CANNOT do:**
${noTouchBullets}
- Do NOT install new packages or add dependencies.
- Do NOT modify test fixtures, test cases, or expected outputs.${secondaryRule}${extraRulesBlock}

**Goal: ${goalVerb} \`${metricName}\`.**

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Removing something and getting equal or better results is a great outcome.

## Eval Command

\`\`\`bash
${evalCommand}
\`\`\`

The score line in stdout looks like: \`${scorePattern}\`
Extract it with: \`${grepMetric}\`${grepSecondary ? `\nSecondary metric: \`${secondaryGrep}\`` : ""}

## Results Format

Log every experiment to \`results.tsv\` (tab-separated). The TSV has this header:

\`\`\`
${tsvHeader}
\`\`\`

- **commit**: short git hash (7 chars)
- **${metricName}**: the score achieved (use \`0\` for crashes)${hasSecondary ? `\n- **${secondaryName}**: the secondary metric value (use \`0\` for crashes)` : ""}
- **status**: \`keep\`, \`discard\`, or \`crash\`
- **description**: short text describing what the experiment tried

## The Experiment Loop

LOOP FOREVER:

1. Look at the git state and results so far for context.
2. Modify ${fileListFormatted} with an experimental idea.
3. \`git commit -m "short description of what you changed"\`
4. Run the experiment:
   \`\`\`bash
   timeout ${timeoutSeconds} ${evalCommand} > run.log 2>&1
   \`\`\`
   IMPORTANT: Always redirect to run.log. Do NOT use tee or let output stream into your context window. It will flood your context and slow you down across experiments.
5. Read the result: \`${grepMetric}\`${grepSecondary}
6. If grep output is empty, the run crashed or timed out. Run \`tail -50 run.log\` to see the error.
7. Record the result in results.tsv.
8. If ${metricName} ${compareOp} compared to the current best, **keep** the commit (advance the branch).
9. If ${metricName} is ${compareRevert}, **discard** and revert: \`git reset --hard HEAD~1\`.

**Timeout**: If a run exceeds ${timeout} minutes, kill it and treat it as a crash.

**Crashes**: Use your judgment. If it's something trivial to fix (typo, missing import), fix and re-run. If the idea is fundamentally broken, log it as \`crash\` and move on. If you can't get things working after 2-3 attempts, give up on that idea.

**NEVER STOP**: Once the loop has begun, do NOT pause to ask the human anything. Do NOT ask "should I keep going?" or "is this a good stopping point?" The human might be asleep and expects you to continue working indefinitely. You are autonomous. If you run out of ideas, think harder — re-read the codebase for new angles, try combining previous near-misses, try more radical changes. The loop runs until the human manually stops you.
`;

  // --- Write files ---

  const outputDir = process.cwd();
  const setupPath = resolve(outputDir, "setup.md");

  if (existsSync(setupPath)) {
    const overwrite = await askYN("setup.md already exists. Overwrite?", "n");
    if (!overwrite) {
      const altPath = resolve(outputDir, "setup.generated.md");
      writeFileSync(altPath, setupMd);
      console.log("\nCreated: setup.generated.md");
    } else {
      writeFileSync(setupPath, setupMd);
      console.log("\nCreated: setup.md");
    }
  } else {
    writeFileSync(setupPath, setupMd);
    console.log("\nCreated: setup.md");
  }

  if (generateEval) {
    const evalPath = resolve(outputDir, "eval.js");
    if (existsSync(evalPath)) {
      console.log("eval.js already exists, skipping.");
    } else {
      const evalTemplate = `// eval.js — read-only, the agent must NOT modify this file
//
// This script answers: "how good is the project right now?"
// It runs your project, measures the result, and prints a score.
//
// Contract: this script must print a line like:
//   ${metricName}: 85.3
// so the agent can extract it with grep.

// TODO: Replace the placeholder below with your actual evaluation logic.

import { execSync } from "child_process";

async function evaluate() {
  // Step 1: Build or run your project
  // e.g. execSync("npm run build", { stdio: "inherit" });

  // Step 2: Measure something
  // e.g. run test cases, measure response time, check pass rate

  // Step 3: Print the score
  const ${metricName} = 0; // replace with your actual measurement
  console.log("---");
  console.log(\`${metricName}: \${${metricName}}\`);${
    hasSecondary
      ? `\n  const ${secondaryName} = 0; // replace with your measurement\n  console.log(\`${secondaryName}: \${${secondaryName}}\`);`
      : ""
  }
}

evaluate().catch((err) => {
  console.error(err);
  process.exit(1);
});
`;
      writeFileSync(evalPath, evalTemplate);
      console.log(
        "Created: eval.js (starter template — fill in your evaluation logic)",
      );
    }
  }

  console.log(`
Done! Next steps:

  1. ${generateEval ? "Fill in eval.js with your actual evaluation logic" : "Make sure your eval script is ready"}
  2. Open your AI coding agent (Claude Code, Codex, etc.) in this directory
  3. Tell it: "Read setup.md and kick off a new experiment. Do the setup first."
  4. Walk away
`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
