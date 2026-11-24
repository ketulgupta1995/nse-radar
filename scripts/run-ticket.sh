#!/usr/bin/env bash
# Run one ticket headless with a smaller model. Usage: scripts/run-ticket.sh N002 [model] ["extra note for the worker"]
# Use this only after a few tickets have gone smoothly in normal (interactive) sessions.
set -euo pipefail
cd "$(dirname "$0")/.."
id="${1:?usage: run-ticket.sh N0NN [model]}"; model="${2:-sonnet}"
file=$(ls tickets/"$id"-*.md 2>/dev/null | head -1) || true
[ -n "${file:-}" ] || { echo "no ticket file for $id"; exit 1; }
mkdir -p logs
log="logs/$id-$(date +%Y%m%d-%H%M).log"
echo "Running $file with $model -> $log"
# Headless sessions can't answer permission prompts, so allow exactly the commands AGENTS.md needs.
# No push, no network tools, no general shell.
allowed=(
  "Bash(.venv/bin/pytest *)" "Bash(.venv/bin/ruff *)" "Bash(.venv/bin/python *)"
  "Bash(npm run build*)" "Bash(npm test*)" "Bash(npx tsc *)" "Bash(npx vitest *)"
  "Bash(git status*)" "Bash(git diff*)" "Bash(git log*)" "Bash(git show*)" "Bash(git add *)" "Bash(git commit *)"
  "Bash(claude --help*)" "Bash(claude --version*)"
  "Bash(ls *)" "Bash(cat *)" "Bash(grep *)" "Bash(find *)" "Bash(head *)" "Bash(tail *)" "Bash(wc *)"
)
prompt="Implement the ticket in $file. Follow AGENTS.md exactly. Finish with the AGENTS.md 'Finishing' steps. Run git as simple single commands (git add <files>, then git commit -m \"...\" -m \"Co-Authored-By: ...\"); never use \$(...), heredocs or && chains with git, which headless mode cannot approve. ${3:-}"
# The prompt goes first: --allowedTools is variadic and would swallow anything after it.
claude -p "$prompt" --model "$model" --permission-mode acceptEdits --allowedTools "${allowed[@]}" \
  < /dev/null 2>&1 | tee "$log"
git log -1 --oneline
