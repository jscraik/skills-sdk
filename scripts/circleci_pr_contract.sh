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
  main_metadata() {
    curl --fail --silent --show-error --retry 3 --connect-timeout 10 --max-time 30 \
      --header 'Accept: application/vnd.github+json' "https://api.github.com/repos/$repo/git/ref/heads/main"
  }
  main_sha() {
    jq -ser 'select(length == 1 and .[0].ref == "refs/heads/main" and .[0].object.type == "commit") | .[0].object.sha' "$1"
  }
  verify_pr_identity() {
    jq -se --arg head "$HEAD_SHA" --arg repo "$repo" \
      'length == 1 and .[0].head.sha == $head and .[0].state == "open" and .[0].base.ref == "main" and
       ((.[0].base.repo.full_name | ascii_downcase) == ($repo | ascii_downcase))' "$1"
  }
  metadata="$(mktemp -d)"
  trap 'rm -rf -- "$metadata"' EXIT
  HEAD_SHA="$CIRCLE_SHA1"
  [[ "$HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]
  # GitHub may calculate its test merge asynchronously after the PR lookup.
  for attempt in 1 2 3 4; do
    pr_metadata > "$metadata/pr.json"
    verify_pr_identity "$metadata/pr.json"
    if jq -e '.mergeable == true and (.merge_commit_sha | type == "string" and test("^[0-9a-f]{40}$"))' \
      "$metadata/pr.json" >/dev/null; then
      break
    fi
    if [[ "$(jq -r '.mergeable' "$metadata/pr.json")" != null || "$attempt" == 4 ]]; then
      echo "GitHub has not supplied a usable test merge" >&2
      exit 1
    fi
    sleep 2
  done
  canonical_merge="$(jq -r .merge_commit_sha "$metadata/pr.json")"
  main_metadata > "$metadata/main.json"
  canonical_main="$(main_sha "$metadata/main.json")"
  [[ "$canonical_main" =~ ^[0-9a-f]{40}$ ]]
  git fetch --no-tags origin "$HEAD_SHA" \
    "+refs/heads/main:refs/remotes/origin/main" "+refs/pull/$PR_NUMBER/merge:refs/ci/pr-merge"
  BASE_SHA="$(git rev-parse --verify 'refs/remotes/origin/main^{commit}')"
  merge_sha="$(git rev-parse --verify 'refs/ci/pr-merge^{commit}')"
  [[ "$BASE_SHA" =~ ^[0-9a-f]{40}$ && "$merge_sha" =~ ^[0-9a-f]{40}$ ]]
  if ! merge_base="$(git rev-parse --verify refs/ci/pr-merge^1)"; then exit 1; fi
  if ! merge_head="$(git rev-parse --verify refs/ci/pr-merge^2)"; then exit 1; fi
  if [[ "$BASE_SHA" != "$canonical_main" ]]; then
    echo "Fetched main does not match GitHub main" >&2
    exit 1
  fi
  if [[ "$merge_sha" != "$canonical_merge" ]]; then
    echo "Fetched merge does not match GitHub test merge" >&2
    exit 1
  fi
  if [[ "$merge_base" != "$BASE_SHA" || "$merge_head" != "$HEAD_SHA" ]] || \
    git rev-parse --verify 'refs/ci/pr-merge^3' >/dev/null 2>&1; then
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
  verify_pr_identity "$metadata/final.json"
  jq -e --arg merge "$merge_sha" \
    '.mergeable == true and .merge_commit_sha == $merge' "$metadata/final.json"
  jq -r '.body // ""' "$metadata/final.json" > "$body_file"
  python3 "$validator" --template "$template" --body-file "$body_file"
  main_metadata > "$metadata/final-main.json"
  final_main="$(main_sha "$metadata/final-main.json")"
  if [[ "$final_main" != "$BASE_SHA" ]]; then
    echo "GitHub main changed during validation preparation" >&2
    exit 1
  fi
  git fetch --no-tags origin "+refs/heads/main:refs/ci/final-main" \
    "+refs/pull/$PR_NUMBER/merge:refs/ci/final-merge"
  if [[ "$(git rev-parse --verify 'refs/ci/final-main^{commit}')" != "$BASE_SHA" || \
    "$(git rev-parse --verify 'refs/ci/final-merge^{commit}')" != "$merge_sha" ]]; then
    echo "PR base or merge changed during validation preparation" >&2
    exit 1
  fi
  git checkout --detach refs/ci/pr-merge
fi
[[ "$scope" == full || "$scope" == docs ]]
printf 'export SDK_CI_SCOPE=%q\n' "$scope" >> "$BASH_ENV"
if [[ -n "${BASE_SHA:-}" ]]; then
  printf 'export SDK_CI_BASE_SHA=%q\n' "$BASE_SHA" >> "$BASH_ENV"
fi
printf 'Validation revision: %s; scope: %s\n' "$(git rev-parse HEAD)" "$scope"
