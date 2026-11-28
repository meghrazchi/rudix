{{/*
Shared helpers for the Rudix chart (S1 only; other tasks add templates/_<task>.tpl).
Contract: docs/roadmap/V0_8_0_IMPLEMENTATION_PLAN.md section 5.2.2.

Helpers that need a component take a dict: (dict "root" $ "component" "api").
Components: frontend, api, mcp, worker-<pool>, beat, migrate, pgbouncer, backup-<kind>.
*/}}

{{- define "rudix.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "rudix.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "rudix.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fails unless the component is one of the names in the contract. */}}
{{- define "rudix.checkComponent" -}}
{{- $component := . | toString -}}
{{- if not (regexMatch "^(frontend|api|mcp|beat|migrate|pgbouncer|config|serviceaccount|worker-[a-z0-9]+|backup-[a-z0-9]+)$" $component) -}}
{{- fail (printf "rudix: unknown component %q" $component) -}}
{{- end -}}
{{- end -}}

{{/* <fullname>-<component>, at most 63 characters. */}}
{{- define "rudix.componentName" -}}
{{- include "rudix.checkComponent" .component -}}
{{- printf "%s-%s" (include "rudix.fullname" .root) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "rudix.selectorLabels" -}}
{{- include "rudix.checkComponent" .component -}}
app.kubernetes.io/name: {{ include "rudix.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "rudix.labels" -}}
helm.sh/chart: {{ include "rudix.chart" .root }}
{{ include "rudix.selectorLabels" . }}
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
app.kubernetes.io/part-of: rudix
{{- end -}}

{{/* Image key for a component: frontend, api (api, mcp, migrate), or worker (the rest). */}}
{{- define "rudix.imageKey" -}}
{{- include "rudix.checkComponent" . -}}
{{- if eq . "frontend" -}}frontend
{{- else if has . (list "api" "mcp" "migrate") -}}api
{{- else if or (eq . "beat") (hasPrefix "worker-" .) (hasPrefix "backup-" .) -}}worker
{{- else -}}
{{- fail (printf "rudix: component %q has no application image" .) -}}
{{- end -}}
{{- end -}}

{{/* registry/repository@sha256:... when a digest is set, else registry/repository:tag. */}}
{{- define "rudix.image" -}}
{{- $images := .root.Values.image -}}
{{- $image := index $images (include "rudix.imageKey" .component) -}}
{{- $repository := printf "%s/%s" (trimSuffix "/" $images.registry) $image.repository -}}
{{- if $image.digest -}}
{{- $digest := $image.digest | toString -}}
{{- if not (regexMatch "^sha256:[a-f0-9]{64}$" $digest) -}}
{{- fail (printf "rudix: image digest for %s must be sha256:<64 hex>" .component) -}}
{{- end -}}
{{- printf "%s@%s" $repository $digest -}}
{{- else -}}
{{- printf "%s:%s" $repository (default .root.Chart.AppVersion (default $images.tag $image.tag) | toString) -}}
{{- end -}}
{{- end -}}

{{- define "rudix.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "rudix.configMapName" -}}
{{- include "rudix.componentName" (dict "root" . "component" "config") -}}
{{- end -}}

{{- define "rudix.frontendConfigMapName" -}}
{{- include "rudix.componentName" (dict "root" . "component" "frontend") -}}
{{- end -}}

{{/*
A quoted ConfigMap value. Numbers from values files arrive as float64, which toString writes
in exponent form (52428800 -> "5.24288e+07"); toJson keeps the plain digits. Null is "".
*/}}
{{- define "rudix.envValue" -}}
{{- if kindIs "float64" . -}}
{{- toJson . | quote -}}
{{- else if kindIs "invalid" . -}}
{{- "" | quote -}}
{{- else -}}
{{- . | toString | quote -}}
{{- end -}}
{{- end -}}

{{- define "rudix.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "rudix.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* envFrom list items: the config ConfigMap and, when set, secrets.existingSecret. */}}
{{- define "rudix.envFrom" -}}
- configMapRef:
    name: {{ include "rudix.configMapName" . }}
{{- with .Values.secrets.existingSecret }}
- secretRef:
    name: {{ . }}
{{- end }}
{{- end -}}

{{/* Pod securityContext; the frontend runs as `node` (1000), backend images as 10001. */}}
{{- define "rudix.podSecurityContext" -}}
{{- $values := .root.Values.podSecurityContext -}}
{{- $user := ternary $values.frontend $values.backend (eq .component "frontend") -}}
runAsNonRoot: true
runAsUser: {{ $user.runAsUser }}
runAsGroup: {{ $user.runAsGroup }}
fsGroup: {{ $user.fsGroup }}
seccompProfile:
  {{- toYaml $values.seccompProfile | nindent 2 }}
{{- end -}}

{{- define "rudix.containerSecurityContext" -}}
{{- $values := .Values.containerSecurityContext -}}
allowPrivilegeEscalation: {{ $values.allowPrivilegeEscalation }}
readOnlyRootFilesystem: {{ $values.readOnlyRootFilesystem }}
runAsNonRoot: true
capabilities:
  {{- toYaml $values.capabilities | nindent 2 }}
{{- end -}}

{{/* A writable /tmp: use "rudix.tmpVolume" under volumes, "rudix.tmpVolumeMount" in mounts. */}}
{{- define "rudix.tmpVolume" -}}
- name: tmp
  emptyDir:
    sizeLimit: {{ .Values.tmpVolume.sizeLimit }}
{{- end -}}

{{- define "rudix.tmpVolumeMount" -}}
- name: tmp
  mountPath: /tmp
{{- end -}}

{{/* Cross-key checks; included once by configmap.yaml. */}}
{{- define "rudix.validate" -}}
{{- $environment := .Values.global.environment | toString -}}
{{- if not (has $environment (list "development" "test" "staging" "production")) -}}
{{- fail (printf "rudix: global.environment %q is not development|test|staging|production" $environment) -}}
{{- end -}}
{{- $configured := (index .Values.config.env "ENVIRONMENT") | default $environment | toString -}}
{{- if ne $configured $environment -}}
{{- fail "rudix: config.env.ENVIRONMENT must equal global.environment" -}}
{{- end -}}
{{- if .Values.secrets.create -}}
{{- fail "rudix: secrets.create is not supported; set secrets.existingSecret to a Secret you manage" -}}
{{- end -}}
{{- if and .Values.metrics.enabled .Values.metrics.requireAuth (not .Values.secrets.existingSecret) -}}
{{- fail "rudix: metrics.requireAuth needs secrets.existingSecret holding metrics.tokenSecretKey" -}}
{{- end -}}
{{- end -}}
