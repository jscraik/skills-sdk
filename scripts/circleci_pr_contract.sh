#!/usr/bin/env bash
set -euo pipefail

# Prepare metadata outside the validation tree and test GitHub's merge result.
scope=full
if [[ -z "${CIRCLE_PULL_REQUEST:-}" ]]; then
  if [[ "$CIRCLE_BRANCH" != main ]]; then
    echo "PR metadata required for non-main validation" >&2
    exit 1
  fi
else
  PR_NUMBER="${CIRCLE_PULL_REQUEST##*/}"
  [[ "$PR_NUMBER" =~ ^[0-9]+$ ]]
  repo="$CIRCLE_PROJECT_USERNAME/$CIRCLE_PROJECT_REPONAME"
  # Public metadata needs no reusable credential in the candidate project.
  pr_metadata() {
    curl --fail --silent --show-error --retry 3 --connect-timeout 10 --max-time 30 \
      --header 'Accept: application/vnd.github+json' "https://api.github.com/repos/$repo/pulls/$PR_NUMBER"
  }
  metadata="$(mktemp -d)"
  trap 'rm -rf -- "$metadata"' EXIT
  pr_metadata > "$metadata/pr.json"
  jq -e --arg head "$CIRCLE_SHA1" '.head.sha == $head and .state == "open"' "$metadata/pr.json"
  BASE_SHA="$(jq -r .base.sha "$metadata/pr.json")"
  HEAD_SHA="$CIRCLE_SHA1"
  [[ "$BASE_SHA" =~ ^[0-9a-f]{40}$ && "$HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]
  git fetch --no-tags origin "$BASE_SHA" "$HEAD_SHA" \
    "+refs/heads/main:refs/remotes/origin/main" "+refs/pull/$PR_NUMBER/merge:refs/ci/pr-merge"
  if ! merge_base="$(git rev-parse --verify refs/ci/pr-merge^1)"; then exit 1; fi
  if ! merge_head="$(git rev-parse --verify refs/ci/pr-merge^2)"; then exit 1; fi
  if [[ "$merge_base" != "$BASE_SHA" || "$merge_head" != "$HEAD_SHA" ]]; then
    echo "PR merge parents do not match live base and head" >&2
    exit 1
  fi
  validator="$metadata/validator.py"
  template="$metadata/template.md"
  body_file="$metadata/body.md"
  git show "$BASE_SHA:.github/scripts/validate_pr_template_body.py" > "$validator"
  git show "$BASE_SHA:.github/PULL_REQUEST_TEMPLATE.md" > "$template"
  for attempt in 1 2 3 4; do
    pr_metadata > "$metadata/body.json"
    jq -r '.body // ""' "$metadata/body.json" > "$body_file"
    if python3 "$validator" --template "$template" --body-file "$body_file"; then
      break
    fi
    if [[ "$attempt" == 4 ]]; then exit 1; fi
    sleep 10
  done
  classifier="$metadata/validation_scope.py"
  if git cat-file -e "$BASE_SHA:scripts/validation_scope.py"; then
    git show "$BASE_SHA:scripts/validation_scope.py" > "$classifier"
  fi
  RUNNER_TEMP="$metadata"
  if [[ -f "$classifier" ]]; then
    head_checkout="$(mktemp -d "$RUNNER_TEMP/sdk-pr-head.XXXXXX")"
    git worktree add --quiet --detach "$head_checkout" "$HEAD_SHA"
    scope="$(cd "$head_checkout" && python3 "$classifier" --base "$BASE_SHA" --head "$HEAD_SHA")"
    git worktree remove "$head_checkout"
  fi
  echo "scope=$scope"
  # Recheck live identity after fetching the merge tree and validating the body.
  pr_metadata > "$metadata/final.json"
  jq -e --arg head "$HEAD_SHA" --arg base "$BASE_SHA" \
    '.head.sha == $head and .base.sha == $base and .state == "open"' "$metadata/final.json"
  jq -r '.body // ""' "$metadata/final.json" > "$body_file"
  python3 "$validator" --template "$template" --body-file "$body_file"
  git checkout --detach refs/ci/pr-merge
fi
[[ "$scope" == full || "$scope" == docs ]]
printf 'export SDK_CI_SCOPE=%q\n' "$scope" >> "$BASH_ENV"
if [[ -n "${BASE_SHA:-}" ]]; then
  printf 'export SDK_CI_BASE_SHA=%q\n' "$BASE_SHA" >> "$BASH_ENV"
fi
printf 'Validation revision: %s; scope: %s\n' "$(git rev-parse HEAD)" "$scope"
