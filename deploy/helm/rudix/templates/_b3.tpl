{{/*
B3 helpers: OpenTelemetry tracing (R08-10).

config.env carries the switches the backend reads (TRACING_ENABLED,
OTEL_EXPORTER_OTLP_ENDPOINT). A key a values file sets must agree with the `tracing` block.
Enabled tracing needs an endpoint, https:// in staging and production unless
TRACING_ALLOW_INSECURE_ENDPOINT is "true" (a private collector). Collector headers come only
from the Secret key OTEL_EXPORTER_OTLP_HEADERS (envFrom keeps the key name).
*/}}
{{- define "rudix.b3.validate" -}}
{{- $env := .Values.config.env -}}
{{- $tracing := .Values.tracing | default dict -}}
{{- $enabled := ($tracing.enabled | default false) | toString -}}
{{- $endpoint := ($tracing.endpoint | default "") | toString -}}
{{- if hasKey $env "TRACING_ENABLED" -}}
{{- if ne (index $env "TRACING_ENABLED" | toString | lower) $enabled -}}
{{- fail (printf "rudix: config.env.TRACING_ENABLED disagrees with tracing.enabled (%s)" $enabled) -}}
{{- end -}}
{{- end -}}
{{- if hasKey $env "OTEL_EXPORTER_OTLP_ENDPOINT" -}}
{{- if ne (index $env "OTEL_EXPORTER_OTLP_ENDPOINT" | toString) $endpoint -}}
{{- fail "rudix: config.env.OTEL_EXPORTER_OTLP_ENDPOINT must equal tracing.endpoint" -}}
{{- end -}}
{{- end -}}
{{- if eq $enabled "true" -}}
{{- if not $endpoint -}}
{{- fail "rudix: tracing.enabled needs tracing.endpoint (an OTLP/HTTP collector URL)" -}}
{{- end -}}
{{- $insecure := (index $env "TRACING_ALLOW_INSECURE_ENDPOINT" | default "false") | toString | lower -}}
{{- $strict := has (.Values.global.environment | toString) (list "staging" "production") -}}
{{- if and $strict (not (hasPrefix "https://" $endpoint)) (ne $insecure "true") -}}
{{- fail "rudix: tracing.endpoint must use https:// in staging and production" -}}
{{- end -}}
{{- end -}}
{{- $headersKey := ($tracing.headersSecretKey | default "OTEL_EXPORTER_OTLP_HEADERS") | toString -}}
{{- if ne $headersKey "OTEL_EXPORTER_OTLP_HEADERS" -}}
{{- fail "rudix: tracing.headersSecretKey must be OTEL_EXPORTER_OTLP_HEADERS (envFrom keeps Secret key names)" -}}
{{- end -}}
{{- end -}}
