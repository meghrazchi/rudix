#!/usr/bin/env bash
# Roll an environment back to a released version (R03-07).
#
# Usage: deploy/scripts/rollback.sh <staging|production> <vX.Y.Z|X.Y.Z>
#
# Resolves immutable digests from the registry and hands them to
# rollback_compose_remote.sh, which swaps the images without running migrations:
#   api       <base>/api:vX.Y.Z
#   worker    <base>/worker:vX.Y.Z
#   frontend  <base>/frontend-<environment>:<commit sha of vX.Y.Z>
# The frontend is resolved by commit because its public URLs are baked in at build
# time: each environment has its own frontend image per commit.
#
# Environment:
#   DEPLOY_REGISTRY, DEPLOY_IMAGE_NAMESPACE   image base <registry>/<namespace>
#   ROLLBACK_COMMIT_SHA     optional; defaults to `git rev-list -n 1 <tag>`
#   ROLLBACK_RESOLVE_ONLY   true: print the digests and stop (no SSH)
#   plus everything rollback_compose_remote.sh needs (DEPLOY_SSH_*, DEPLOY_APP_PATH,
#   DEPLOY_REGISTRY_USER, DEPLOY_REGISTRY_PASSWORD, <ENV>_SSH_KNOWN_HOSTS).
set -euo pipefail

usage() {
  echo "Usage: $0 <staging|production> <vX.Y.Z>" >&2
  exit 2
}

environment_name="${1:-}"
version="${2:-}"
case "$environment_name" in
  staging | production) ;;
  *) usage ;;
esac
if [[ ! "${version#v}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc\.?[0-9]+)?$ ]]; then
  echo "Version must look like vX.Y.Z (got: ${version:-<empty>})" >&2
  usage
fi
tag="v${version#v}"

for var_name in DEPLOY_REGISTRY DEPLOY_IMAGE_NAMESPACE; do
  if [ -z "${!var_name:-}" ]; then
    echo "Missing required variable: ${var_name}" >&2
    exit 1
  fi
done
image_base="${DEPLOY_REGISTRY}/${DEPLOY_IMAGE_NAMESPACE}"

commit_sha="${ROLLBACK_COMMIT_SHA:-}"
if [ -z "$commit_sha" ]; then
  if ! commit_sha="$(git rev-list -n 1 "refs/tags/${tag}" 2>/dev/null)" || [ -z "$commit_sha" ]; then
    echo "Tag ${tag} not found locally; fetch tags (fetch-depth: 0) or set ROLLBACK_COMMIT_SHA." >&2
    exit 1
  fi
fi

# Prints <repo>@sha256:... for a tag, or fails when the tag does not exist.
resolve_digest() {
  local ref="$1" digest
  if ! digest="$(docker buildx imagetools inspect --format '{{ .Manifest.Digest }}' "$ref")" \
    || [[ "$digest" != sha256:* ]]; then
    echo "Could not resolve a digest for ${ref}" >&2
    return 1
  fi
  printf '%s@%s\n' "${ref%:*}" "$digest"
}

api_image="$(resolve_digest "${image_base}/api:${tag}")"
worker_image="$(resolve_digest "${image_base}/worker:${tag}")"
frontend_image="$(resolve_digest "${image_base}/frontend-${environment_name}:${commit_sha}")"

echo "Rollback ${environment_name} to ${tag} (commit ${commit_sha}):"
echo "  api:      ${api_image}"
echo "  worker:   ${worker_image}"
echo "  frontend: ${frontend_image}"

cat <<EOF
Database: this rollback does not run migrations. Before continuing, compare the
deployed revision with the target release:
  alembic current                                  (on the host, api container)
  git diff --stat ${tag} -- backend/alembic/versions  (migrations added since ${tag})
  alembic history -r <${tag} head>:<current>        (what each newer revision does)
Old code on a newer schema is safe only when every newer migration is additive
(new tables, nullable columns, indexes). Downgrades are never automatic; for a
migration that dropped or rewrote data, restore the database from backup.
EOF

if [ "${ROLLBACK_RESOLVE_ONLY:-false}" = "true" ]; then
  exit 0
fi

DEPLOY_ENVIRONMENT="$environment_name" \
  ROLLBACK_API_IMAGE="$api_image" \
  ROLLBACK_WORKER_IMAGE="$worker_image" \
  ROLLBACK_FRONTEND_IMAGE="$frontend_image" \
  "$(dirname "$0")/rollback_compose_remote.sh"
