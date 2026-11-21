#!/usr/bin/env bash
set -euo pipefail

# This file's checksum also keys the Linux x64 CircleCI archive cache.
readonly mise_url=https://github.com/jdx/mise/releases/download/v2026.8.14/mise-v2026.8.14-linux-x64.tar.gz
readonly mise_sha256=64d5f34aeb7a4e0e327dc1c9be66cd8162e14899a47b11901154a100285a3d61
readonly mise_archive=/tmp/mise.tar.gz

verify_archive() {
  [[ -f "$1" && ! -L "$1" ]] &&
    printf '%s  %s\n' "$mise_sha256" "$1" | sha256sum --check --status
}

if verify_archive "$mise_archive"; then
  printf '%s\n' 'mise archive cache hit (SHA-256 verified)'
else
  scratch="$(mktemp -d /tmp/sdk-mise.XXXXXXXX)"
  trap 'rm -rf -- "$scratch"' EXIT
  printf '%s\n' 'mise archive cache miss or invalid entry; downloading the pinned release'
  curl --fail --location --retry 3 --max-time 120 "$mise_url" -o "$scratch/mise.tar.gz"
  if ! verify_archive "$scratch/mise.tar.gz"; then
    printf '%s\n' 'mise release archive failed SHA-256 verification' >&2
    exit 1
  fi
  if [[ -d "$mise_archive" ]]; then
    printf '%s\n' 'mise cache archive path is a directory' >&2
    exit 1
  fi
  mv -f -- "$scratch/mise.tar.gz" "$mise_archive"
fi
