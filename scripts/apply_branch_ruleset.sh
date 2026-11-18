#!/usr/bin/env bash
# Apply .github/rulesets/main.json to this repository: create the ruleset, or update it in place,
# so the protection of main is reviewed code like everything else. Idempotent.
#
#   scripts/apply_branch_ruleset.sh
#
# Needs gh logged in as an admin of the repository. integration_id 15368 is GitHub Actions: only
# check runs from Actions satisfy the required checks, not a status anyone could post.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
file=.github/rulesets/main.json
repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
name="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["name"])' "$file")"
id="$(gh api "repos/$repo/rulesets" --jq ".[] | select(.name == \"$name\") | .id")"
if [ -n "$id" ]; then
  gh api --method PUT "repos/$repo/rulesets/$id" --input "$file" >/dev/null
  echo "updated ruleset '$name' ($id) on $repo"
else
  id="$(gh api --method POST "repos/$repo/rulesets" --input "$file" --jq .id)"
  echo "created ruleset '$name' ($id) on $repo"
fi
gh api "repos/$repo/rulesets/$id" \
  --jq '{name, enforcement, bypass: .bypass_actors, rules: [.rules[].type],
         checks: [.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context]}'
