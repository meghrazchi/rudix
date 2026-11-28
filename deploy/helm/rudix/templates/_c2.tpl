{{/*
C2 helpers: database settings and the optional PgBouncer pooler (0.8.0, R08-04). docs/28,
"Database: managed Postgres, replica, pooler".
*/}}

{{/* "true" or "false": DB_PGBOUNCER_MODE as the application will read it. */}}
{{- define "rudix.c2.envPgbouncerMode" -}}
{{- $raw := index .Values.config.env "DB_PGBOUNCER_MODE" | default "false" | toString | lower -}}
{{- if has $raw (list "true" "1" "yes" "on") -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{/* Cross-key checks for C2; included once by pgbouncer/deployment.yaml. */}}
{{- define "rudix.c2.validate" -}}
{{- $database := .Values.database | default dict -}}
{{- $mode := ternary "true" "false" (eq (toString $database.pgbouncerMode) "true") -}}
{{- if ne $mode (include "rudix.c2.envPgbouncerMode" .) -}}
{{- fail "rudix: database.pgbouncerMode must equal config.env.DB_PGBOUNCER_MODE" -}}
{{- end -}}
{{- if .Values.pgbouncer.enabled -}}
{{- $_ := required "rudix: pgbouncer.image is required when pgbouncer.enabled (no default image is guessed)" .Values.pgbouncer.image -}}
{{- $_ := required "rudix: pgbouncer.configSecretName is required when pgbouncer.enabled (a Secret with pgbouncer.ini and userlist.txt)" .Values.pgbouncer.configSecretName -}}
{{- if ne $mode "true" -}}
{{- fail "rudix: pgbouncer.enabled needs database.pgbouncerMode and config.env.DB_PGBOUNCER_MODE true (transaction pooling breaks prepared statements otherwise)" -}}
{{- end -}}
{{- if lt (int .Values.pgbouncer.replicas) 1 -}}
{{- fail "rudix: pgbouncer.replicas must be at least 1 when pgbouncer.enabled" -}}
{{- end -}}
{{- if and .Values.migrations.enabled (not .Values.migrations.useMigrationUrl) -}}
{{- fail "rudix: pgbouncer.enabled needs migrations.useMigrationUrl; migrations connect to PostgreSQL directly, not through the transaction pooler" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Server connections PgBouncer opens during a rolling update: (replicas + surge) x pool. */}}
{{- define "rudix.c2.poolerServerConnections" -}}
{{- $pgbouncer := .Values.pgbouncer -}}
{{- $replicas := int $pgbouncer.replicas -}}
{{- $surge := int (include "rudix.c1.surge" (dict "surge" .Values.rollout.web.maxSurge "replicas" $replicas)) -}}
{{- mul (add $replicas $surge) (add (int $pgbouncer.defaultPoolSize) (int $pgbouncer.reservePoolSize)) -}}
{{- end -}}

{{/* Client connections PgBouncer accepts across its steady-state replicas. */}}
{{- define "rudix.c2.poolerClientLimit" -}}
{{- mul (int .Values.pgbouncer.replicas) (int .Values.pgbouncer.maxClientConnections) -}}
{{- end -}}
