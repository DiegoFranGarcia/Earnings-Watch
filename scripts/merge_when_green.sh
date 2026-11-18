#!/usr/bin/env bash
# Merge the current branch's pull request once CI has passed on the commit you last pushed.
#
#   scripts/merge_when_green.sh
#
# Waits (up to 5 minutes) for GitHub to start CI on exactly that commit, watches that run, and
# squash-merges only if it succeeded; then switches to main and pulls. Waiting on the commit, not
# the branch, matters: after a second push, the branch's newest run can still be the first one.
# The ruleset on main enforces the same checks; this only saves watching for them.
set -euo pipefail
branch="$(git branch --show-current)"
[ "$branch" != main ] || { echo "on main: switch to the pull request's branch" >&2; exit 2; }
head="$(git rev-parse HEAD)"
[ "$head" = "$(git rev-parse '@{u}' 2>/dev/null)" ] \
  || { echo "${head:0:12} is not what origin has for $branch: git push first" >&2; exit 2; }

echo "waiting for CI on $branch at ${head:0:12}"
run=""
for _ in $(seq 60); do
  # A failed query (a network blip) counts as "not yet": the loop asks again.
  run="$(gh run list --workflow CI --commit "$head" --limit 1 --json databaseId --jq '.[].databaseId')" \
    || run=""
  [ -n "$run" ] && break
  sleep 5
done
[ -n "$run" ] || { echo "no CI run started for ${head:0:12} within 5 minutes" >&2; exit 1; }

gh run watch "$run" --exit-status
gh pr merge "$branch" --squash --delete-branch
git switch main
git pull --ff-only
