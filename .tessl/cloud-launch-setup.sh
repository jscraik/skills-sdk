#!/usr/bin/env bash
set -eo pipefail

fail() {
    printf 'Codex setup check: %s\n' "$1" >&2
    exit 1
}

[[ ${AGENT:-} == codex ]] || fail 'expected AGENT=codex'
root=$(pwd -P)
checkout=$(git rev-parse --show-toplevel 2>/dev/null) || fail 'checkout not found'
[[ "$checkout" == "$root" ]] || fail 'hook must run at the checkout root'
case "$(git remote get-url origin 2>/dev/null)" in
    https://github.com/jscraik/skills-sdk|https://github.com/jscraik/skills-sdk.git|git@github.com:jscraik/skills-sdk.git) ;;
    *) fail 'origin does not match the expected Skills SDK repository' ;;
esac

workdir=$(cd -- "${WORKDIR:-.}" 2>/dev/null && pwd -P) || fail 'WORKDIR is not readable'
case "$workdir" in
    "$root"|"$root/"*) ;;
    *) fail 'WORKDIR is outside the checkout' ;;
esac

task=.tessl/codex-setup-check.md
[[ -d "$workdir/.tessl" && ! -L "$workdir/.tessl" ]] || fail 'task directory is absent or linked'
[[ -f "$workdir/$task" && -r "$workdir/$task" && ! -L "$workdir/$task" ]] || fail 'expected task file is missing, unreadable or linked'
revision=$(git rev-parse --verify HEAD) || fail 'checkout revision is unavailable'
printf 'agent=codex repo=jscraik/skills-sdk revision=%s workdir=%q task=%s readable=yes\n' \
    "$revision" "${workdir#"$root"}" "$task"
