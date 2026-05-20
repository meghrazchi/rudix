#!/bin/sh
set -eu

environment_name="${1:-}"
release_sha="${2:-}"

if [ -z "${SENTRY_DSN:-}" ]; then
  echo "SENTRY_DSN is not configured; skipping Sentry release tagging."
  exit 0
fi

if [ -z "${SENTRY_AUTH_TOKEN:-}" ] || [ -z "${SENTRY_ORG:-}" ] || [ -z "${SENTRY_PROJECT:-}" ]; then
  echo "Sentry release tagging is enabled, but SENTRY_AUTH_TOKEN/SENTRY_ORG/SENTRY_PROJECT are missing." >&2
  exit 1
fi

if [ -z "$environment_name" ] || [ -z "$release_sha" ]; then
  echo "Usage: $0 <environment> <release_sha>" >&2
  exit 1
fi

curl -sL https://sentry.io/get-cli/ | sh
export PATH="$HOME/.local/bin:$PATH"

sentry-cli releases new "$release_sha"
sentry-cli releases set-commits "$release_sha" --auto || true
sentry-cli releases deploys "$release_sha" new -e "$environment_name"

echo "Tagged Sentry release ${release_sha} for ${environment_name}."
