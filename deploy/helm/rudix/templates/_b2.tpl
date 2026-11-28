{{/*
B2 helpers: metrics scrape (R08-09, contract 5.2.8).
*/}}

{{/* Standard labels for the ServiceMonitors, which span components. */}}
{{- define "rudix.b2.labels" -}}
helm.sh/chart: {{ include "rudix.chart" . }}
{{ include "rudix.c1.releaseSelector" . }}
app.kubernetes.io/component: metrics
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: rudix
{{- end -}}

{{/*
config.env carries the metrics switches the backend reads (METRICS_ENABLED,
METRICS_REQUIRE_AUTH, WORKER_METRICS_ENABLED, WORKER_METRICS_MULTIPROCESS). While metrics are
enabled, a switch a values file sets must agree with the `metrics` block, so the pods serve
what the ServiceMonitors scrape; staging and production must require the token. With
metrics disabled nothing is scraped, so the switches are not checked (and no ServiceMonitor
renders even when serviceMonitor.enabled is true).
*/}}
{{- define "rudix.b2.validate" -}}
{{- $env := .Values.config.env -}}
{{- $metrics := .Values.metrics -}}
{{- $multiprocess := (($metrics.workers | default dict).multiprocess | default false) | toString -}}
{{- $expected := dict "WORKER_METRICS_MULTIPROCESS" $multiprocess -}}
{{- if $metrics.enabled -}}
{{- $_ := set $expected "METRICS_ENABLED" "true" -}}
{{- $_ := set $expected "WORKER_METRICS_ENABLED" "true" -}}
{{- $_ := set $expected "METRICS_REQUIRE_AUTH" ($metrics.requireAuth | toString) -}}
{{- end -}}
{{- range $key, $want := $expected -}}
{{- if hasKey $env $key -}}
{{- $got := index $env $key | toString | lower -}}
{{- if ne $got $want -}}
{{- fail (printf "rudix: config.env.%s=%s disagrees with the metrics block (%s)" $key $got $want) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if and $metrics.enabled (not $metrics.requireAuth) (has (.Values.global.environment | toString) (list "staging" "production")) -}}
{{- fail "rudix: metrics.requireAuth must be true in staging and production (contract 5.2.8)" -}}
{{- end -}}
{{- end -}}

{{/* One ServiceMonitor endpoint: (dict "root" $ "port" <name> "job" <job label>). */}}
{{- define "rudix.b2.endpoint" -}}
{{- $root := .root -}}
{{- $sm := $root.Values.metrics.serviceMonitor -}}
- port: {{ .port }}
  path: /metrics
  scheme: http
  interval: {{ $sm.interval | default "30s" }}
  scrapeTimeout: {{ $sm.scrapeTimeout | default "10s" }}
  {{- if $root.Values.metrics.requireAuth }}
  bearerTokenSecret:
    name: {{ $root.Values.secrets.existingSecret }}
    key: {{ $root.Values.metrics.tokenSecretKey }}
  {{- end }}
  relabelings:
    # Same job names as Compose (prometheus.yml), so the rule files work unchanged.
    - action: replace
      targetLabel: job
      replacement: {{ .job }}
{{- end -}}
