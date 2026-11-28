{{/*
D1 (R08-11, R08-12): secrets, request-time frontend configuration, CDN.
Checks run from externalsecret.yaml on every render, whether or not the ExternalSecret is on.
*/}}

{{/* Names that are fixed when the frontend image is built; runtimeConfig.env cannot change them. */}}
{{- define "rudix.d1.buildTimeFrontendKeys" -}}
{{- list "NEXT_PUBLIC_ASSET_PREFIX" "PUBLIC_ASSET_CACHE_CONTROL" "NEXT_PUBLIC_PUBLIC_SITE_URL" | toJson -}}
{{- end -}}

{{- define "rudix.d1.validate" -}}
{{- $env := .Values.runtimeConfig.env | default dict -}}
{{- range $key := (include "rudix.d1.buildTimeFrontendKeys" . | fromJsonArray) -}}
{{- if hasKey $env $key -}}
{{- fail (printf "rudix: runtimeConfig.env.%s is fixed when the frontend image is built; set it as a build argument (see cdn)" $key) -}}
{{- end -}}
{{- end -}}
{{- $source := (index $env "NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE") | default "build" | toString | lower -}}
{{- if not (has $source (list "build" "request")) -}}
{{- fail "rudix: runtimeConfig.env.NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE must be build or request" -}}
{{- end -}}
{{- $cdn := .Values.cdn | default dict -}}
{{- with $cdn.assetPrefix -}}
{{- if not (hasPrefix "https://" (toString .)) -}}
{{- fail "rudix: cdn.assetPrefix must be an https:// URL" -}}
{{- end -}}
{{- end -}}
{{- with $cdn.publicAssetCacheControl -}}
{{- if contains "immutable" (lower (toString .)) -}}
{{- fail "rudix: cdn.publicAssetCacheControl must not be immutable (public assets are not content-hashed)" -}}
{{- end -}}
{{- end -}}
{{- $external := .Values.secrets.externalSecret | default dict -}}
{{- if $external.enabled -}}
{{- if not .Values.secrets.existingSecret -}}
{{- fail "rudix: secrets.externalSecret needs secrets.existingSecret as the target Secret name" -}}
{{- end -}}
{{- $store := $external.secretStoreRef | default dict -}}
{{- if not $store.name -}}
{{- fail "rudix: secrets.externalSecret.secretStoreRef.name is required" -}}
{{- end -}}
{{- if not (has ($store.kind | default "") (list "SecretStore" "ClusterSecretStore")) -}}
{{- fail "rudix: secrets.externalSecret.secretStoreRef.kind must be SecretStore or ClusterSecretStore" -}}
{{- end -}}
{{- if not $external.data -}}
{{- fail "rudix: secrets.externalSecret.data must list at least one secretKey" -}}
{{- end -}}
{{- range $external.data -}}
{{- if or (not .secretKey) (not (and .remoteRef .remoteRef.key)) -}}
{{- fail "rudix: every secrets.externalSecret.data item needs secretKey and remoteRef.key" -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
