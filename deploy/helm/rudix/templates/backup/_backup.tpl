{{- /*
Backup CronJobs (R08-06, owner A2). One CronJob per enabled kind runs
`python scripts/backup_run.py --kind <kind>` in the worker image: it encrypts the artifact
client-side (AES-256-GCM), uploads it to the backup bucket, and writes the kind's marker.
The encryption key comes from a Secret mounted as a read-only file, never from values or env.
*/ -}}

{{/* Kinds in render order. */}}
{{- define "rudix.backup.kinds" -}}postgres,qdrant,objects{{- end -}}

{{/* Cross-key checks; included once by backup/cronjobs.yaml. */}}
{{- define "rudix.backup.validate" -}}
{{- $backup := .Values.backup -}}
{{- if $backup.enabled -}}
{{- $_ := required "rudix: backup.encryptionKeySecret.name is required when backup.enabled (a Secret holding the backup key file)" $backup.encryptionKeySecret.name -}}
{{- $_ := required "rudix: backup.encryptionKeySecret.key is required when backup.enabled" $backup.encryptionKeySecret.key -}}
{{- $_ := required "rudix: backup.bucket is required when backup.enabled" $backup.bucket -}}
{{- if ne (toString $backup.concurrencyPolicy) "Forbid" -}}
{{- fail "rudix: backup.concurrencyPolicy must be Forbid; two runs of one kind would race on its marker" -}}
{{- end -}}
{{- if and $backup.postgres.enabled (not $.Values.secrets.existingSecret) -}}
{{- fail "rudix: backup.postgres.enabled needs secrets.existingSecret holding backup.postgres.databaseUrlSecretKey" -}}
{{- end -}}
{{- end -}}
{{- /* The freshness beat task runs in the worker pods, which get config.env but not the
CronJob-only BACKUP_BUCKET and BACKUP_PREFIX: it must find the same markers. */ -}}
{{- $env := .Values.config.env | default dict -}}
{{- if eq (toString ((index $env "BACKUP_FRESHNESS_CHECK_ENABLED") | default "")) "true" -}}
{{- $envBucket := toString ((index $env "BACKUP_BUCKET") | default "") -}}
{{- $envPrefix := toString ((index $env "BACKUP_PREFIX") | default "rudix") -}}
{{- if not $envBucket -}}
{{- fail "rudix: config.env.BACKUP_FRESHNESS_CHECK_ENABLED needs config.env.BACKUP_BUCKET: the freshness task reads the markers from the worker pods" -}}
{{- end -}}
{{- if and $backup.enabled (or (ne $envBucket (toString $backup.bucket)) (ne $envPrefix (toString $backup.prefix))) -}}
{{- fail "rudix: config.env.BACKUP_BUCKET and BACKUP_PREFIX must equal backup.bucket and backup.prefix, or the freshness task reads other markers" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* The postgres:16 image used by the dump initContainer (digest wins over tag). */}}
{{- define "rudix.backup.postgresImage" -}}
{{- $image := .Values.backup.postgres.image -}}
{{- if $image.digest -}}
{{- if not (regexMatch "^sha256:[a-f0-9]{64}$" (toString $image.digest)) -}}
{{- fail "rudix: backup.postgres.image.digest must be sha256:<64 hex>" -}}
{{- end -}}
{{- printf "%s@%s" $image.repository $image.digest -}}
{{- else -}}
{{- printf "%s:%s" $image.repository (toString $image.tag) -}}
{{- end -}}
{{- end -}}

{{/* Mount path of the key file. */}}
{{- define "rudix.backup.keyPath" -}}
{{- printf "/run/secrets/rudix-backup/%s" .Values.backup.encryptionKeySecret.key -}}
{{- end -}}
