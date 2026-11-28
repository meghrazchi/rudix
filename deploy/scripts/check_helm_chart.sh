#!/bin/sh
# Lints and renders the Rudix Helm chart (0.8.0, S1).
#
# Runs `helm lint --strict` and `helm template` for the defaults, values-staging.yaml,
# values-production.yaml, and every ci/*-values.yaml. Rendered manifests are written to
# $RENDER_DIR (CI passes it to kubeconform) or to a temporary directory that is removed on
# exit. Nothing is installed and no cluster is contacted. Exits non-zero on the first failure.
#
#   deploy/scripts/check_helm_chart.sh
#   RENDER_DIR=/tmp/helm deploy/scripts/check_helm_chart.sh
#   HELM_BIN=/opt/helm/helm deploy/scripts/check_helm_chart.sh
set -eu

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
chart_dir="$repo_root/deploy/helm/rudix"
helm_bin="${HELM_BIN:-helm}"
release="${HELM_RELEASE_NAME:-rudix}"

if ! command -v "$helm_bin" >/dev/null 2>&1; then
  echo "check_helm_chart: helm not found (looked for '$helm_bin'); install Helm 3 or set HELM_BIN" >&2
  exit 2
fi

if [ -n "${RENDER_DIR:-}" ]; then
  render_dir="$RENDER_DIR"
  mkdir -p "$render_dir"
else
  render_dir="$(mktemp -d)"
  trap 'rm -rf "$render_dir"' EXIT
fi

# One entry per line: a label and the values file (empty for the chart defaults).
cases="defaults|"
cases="$cases
staging|$chart_dir/values-staging.yaml
production|$chart_dir/values-production.yaml"
for file in "$chart_dir"/ci/*-values.yaml; do
  [ -f "$file" ] || continue
  name="$(basename "$file" .yaml)"
  cases="$cases
ci-$name|$file"
done

failed=0
old_ifs="$IFS"
IFS='
'
for entry in $cases; do
  IFS="$old_ifs"
  label="${entry%%|*}"
  values="${entry#*|}"
  out="$render_dir/$label.yaml"
  if [ -n "$values" ]; then
    set -- -f "$values"
  else
    set --
  fi
  echo "==> $label"
  if ! "$helm_bin" lint --strict "$chart_dir" "$@"; then
    echo "check_helm_chart: helm lint failed for $label" >&2
    failed=1
    continue
  fi
  if ! "$helm_bin" template "$release" "$chart_dir" --namespace rudix "$@" >"$out"; then
    echo "check_helm_chart: helm template failed for $label" >&2
    failed=1
    continue
  fi
  echo "    rendered $(grep -c '^kind:' "$out") objects to $out"
done
IFS="$old_ifs"

if [ "$failed" -ne 0 ]; then
  echo "check_helm_chart: FAILED" >&2
  exit 1
fi
echo "check_helm_chart: OK"
