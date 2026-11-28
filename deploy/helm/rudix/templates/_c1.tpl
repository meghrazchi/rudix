{{/*
C1 helpers: workloads, rollout, autoscaling, network policy, connection budget (0.8.0).
Contracts: docs/roadmap/V0_8_0_IMPLEMENTATION_PLAN.md 5.2.2, 5.2.5, 5.2.6; docs/28.
*/}}

{{/* Enabled worker pool names, sorted. */}}
{{- define "rudix.c1.poolNames" -}}
{{- $names := list -}}
{{- range $name, $pool := .Values.workers.pools -}}
{{- if $pool.enabled -}}
{{- $names = append $names $name -}}
{{- end -}}
{{- end -}}
{{- $names | sortAlpha | join "," -}}
{{- end -}}

{{- define "rudix.c1.kedaEnabled" -}}
{{- if and .Values.autoscaling.enabled (eq (toString .Values.autoscaling.mode) "keda") -}}true{{- end -}}
{{- end -}}

{{/* Ceiling of a Deployment's maxSurge ("25%" or an integer) for a replica count. */}}
{{- define "rudix.c1.surge" -}}
{{- $value := toString .surge -}}
{{- $replicas := int .replicas -}}
{{- if hasSuffix "%" $value -}}
{{- $percent := int (trimSuffix "%" $value) -}}
{{- div (add (mul $replicas $percent) 99) 100 -}}
{{- else -}}
{{- int $value -}}
{{- end -}}
{{- end -}}

{{/* Largest replica count of the api (autoscaling maximum when autoscaling is on). */}}
{{- define "rudix.c1.apiMaxReplicas" -}}
{{- if .Values.autoscaling.enabled -}}
{{- int .Values.autoscaling.api.maxReplicas -}}
{{- else -}}
{{- int .Values.api.replicas -}}
{{- end -}}
{{- end -}}

{{/* Largest replica count of one worker pool: (dict "root" $ "name" <pool>). */}}
{{- define "rudix.c1.poolMaxReplicas" -}}
{{- $pool := index .root.Values.workers.pools .name -}}
{{- $scaling := index (.root.Values.autoscaling.workers.pools | default dict) .name | default dict -}}
{{- if and (include "rudix.c1.kedaEnabled" .root) $scaling.maxReplicas -}}
{{- int $scaling.maxReplicas -}}
{{- else -}}
{{- int $pool.replicas -}}
{{- end -}}
{{- end -}}

{{/*
Worst-case PostgreSQL connections of the release, during a rolling update (docs/28):
  per process = (DB_POOL_SIZE + DB_MAX_OVERFLOW) x enginesPerProcess
  api     = (max replicas + surge) x per process          (one uvicorn process per pod)
  mcp     = (replicas + surge) x per process              (when enabled)
  workers = sum over pools of (max replicas + surge) x (concurrency + 1) x per process
            (each prefork child builds its own pool after fork; the main process has one too)
  beat    = 1 x per process
  migrate = 1                                             (alembic uses NullPool)
*/}}
{{- define "rudix.c1.connectionWorstCase" -}}
{{- $env := .Values.config.env -}}
{{- $budget := .Values.connectionBudget -}}
{{- $poolSize := int (default $budget.defaultPoolSize (index $env "DB_POOL_SIZE")) -}}
{{- $overflow := int (default $budget.defaultMaxOverflow (index $env "DB_MAX_OVERFLOW")) -}}
{{- $perProcess := mul (add $poolSize $overflow) (int (default 1 $budget.enginesPerProcess)) -}}
{{- $webSurge := .Values.rollout.web.maxSurge -}}
{{- $apiMax := int (include "rudix.c1.apiMaxReplicas" .) -}}
{{- $apiSurge := int (include "rudix.c1.surge" (dict "surge" $webSurge "replicas" $apiMax)) -}}
{{- $total := mul (add $apiMax $apiSurge) $perProcess -}}
{{- if .Values.mcp.enabled -}}
{{- $mcp := int .Values.mcp.replicas -}}
{{- $mcpSurge := int (include "rudix.c1.surge" (dict "surge" $webSurge "replicas" $mcp)) -}}
{{- $total = add $total (mul (add $mcp $mcpSurge) $perProcess) -}}
{{- end -}}
{{- range $name := splitList "," (include "rudix.c1.poolNames" .) -}}
{{- if $name -}}
{{- $pool := index $.Values.workers.pools $name -}}
{{- $max := int (include "rudix.c1.poolMaxReplicas" (dict "root" $ "name" $name)) -}}
{{- $workerSurge := $.Values.rollout.workers.maxSurge -}}
{{- $surge := int (include "rudix.c1.surge" (dict "surge" $workerSurge "replicas" $max)) -}}
{{- $processes := add (int $pool.concurrency) 1 -}}
{{- $total = add $total (mul (mul (add $max $surge) $processes) $perProcess) -}}
{{- end -}}
{{- end -}}
{{- $total = add $total $perProcess 1 -}}
{{- $total -}}
{{- end -}}

{{/* Cross-key checks for C1; included once by api/deployment.yaml. */}}
{{- define "rudix.c1.validate" -}}
{{- $api := .Values.api -}}
{{- $apiBudget := add (int $api.preStopSleepSeconds) (int $api.gracefulShutdownSeconds) (int $api.drainSeconds) 5 -}}
{{- if gt $apiBudget (int $api.terminationGracePeriodSeconds) -}}
{{- fail (printf "rudix: api preStopSleepSeconds + gracefulShutdownSeconds + drainSeconds + 5 = %d exceeds terminationGracePeriodSeconds %d (contract 5.2.5)" $apiBudget (int $api.terminationGracePeriodSeconds)) -}}
{{- end -}}
{{- range $component := list "frontend" "mcp" -}}
{{- $values := index $.Values $component -}}
{{- if ge (int $values.preStopSleepSeconds) (int $values.terminationGracePeriodSeconds) -}}
{{- fail (printf "rudix: %s preStopSleepSeconds must be below terminationGracePeriodSeconds" $component) -}}
{{- end -}}
{{- end -}}
{{- if ne (int .Values.beat.replicas) 1 -}}
{{- fail "rudix: beat.replicas must be 1; a second beat schedules every task twice" -}}
{{- end -}}
{{- if .Values.autoscaling.enabled -}}
{{- if not (has (toString .Values.autoscaling.mode) (list "keda" "hpa")) -}}
{{- fail "rudix: autoscaling.mode must be keda or hpa" -}}
{{- end -}}
{{- if lt (int .Values.autoscaling.api.minReplicas) 2 -}}
{{- fail "rudix: autoscaling.api.minReplicas must be at least 2" -}}
{{- end -}}
{{- if include "rudix.c1.kedaEnabled" . -}}
{{- $_ := required "rudix: autoscaling.prometheus.serverAddress is required when autoscaling.mode is keda" .Values.autoscaling.prometheus.serverAddress -}}
{{- if not .Values.metrics.enabled -}}
{{- fail "rudix: autoscaling.mode keda needs metrics.enabled; without scraped api and worker metrics every Prometheus trigger reads 0 and the pools never scale out" -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if and .Values.migrations.enabled .Values.migrations.useMigrationUrl (not .Values.secrets.existingSecret) -}}
{{- fail "rudix: migrations.useMigrationUrl needs secrets.existingSecret holding migrations.migrationUrlSecretKey" -}}
{{- end -}}
{{- $limit := int .Values.connectionBudget.maxDatabaseConnections -}}
{{- if gt $limit 0 -}}
{{- $worst := int (include "rudix.c1.connectionWorstCase" .) -}}
{{- if gt $worst $limit -}}
{{- fail (printf "rudix: worst-case database connections %d exceed connectionBudget.maxDatabaseConnections %d; lower replicas, concurrency, DB_POOL_SIZE or DB_MAX_OVERFLOW, or add a pooler (docs/28)" $worst $limit) -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Pod-level fields shared by every C1 workload: (dict "root" $ "component" <name>). */}}
{{- define "rudix.c1.podCommon" -}}
serviceAccountName: {{ include "rudix.serviceAccountName" .root }}
automountServiceAccountToken: false
enableServiceLinks: false
securityContext:
  {{- include "rudix.podSecurityContext" . | nindent 2 }}
{{- include "rudix.imagePullSecrets" .root }}
{{- end -}}

{{/* nodeSelector and tolerations from a component's values (the dict passed as `values`). */}}
{{- define "rudix.c1.scheduling" -}}
{{- with .values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{/* Soft anti-affinity and topology spread across nodes: (dict "root" $ "component" <name>). */}}
{{- define "rudix.c1.spread" -}}
{{- $rollout := .root.Values.rollout -}}
{{- if $rollout.spreadAcrossNodes }}
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          topologyKey: {{ $rollout.topologyKey }}
          labelSelector:
            matchLabels:
              {{- include "rudix.selectorLabels" . | nindent 14 }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: {{ $rollout.topologyKey }}
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "rudix.selectorLabels" . | nindent 8 }}
{{- end }}
{{- end -}}

{{/* RollingUpdate strategy: (dict "root" $ "kind" "web"|"workers"). */}}
{{- define "rudix.c1.rollingStrategy" -}}
{{- $values := index .root.Values.rollout .kind -}}
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: {{ $values.maxUnavailable }}
    maxSurge: {{ $values.maxSurge }}
minReadySeconds: {{ .root.Values.rollout.minReadySeconds }}
revisionHistoryLimit: {{ .root.Values.rollout.revisionHistoryLimit }}
progressDeadlineSeconds: {{ .root.Values.rollout.progressDeadlineSeconds }}
{{- end -}}

{{/* Components that may reach data stores: api, mcp, every worker pool, beat, migrate, backups. */}}
{{- define "rudix.c1.dataClientComponents" -}}
{{- $components := list "api" "mcp" "beat" "migrate" -}}
{{- range $name := splitList "," (include "rudix.c1.poolNames" .) -}}
{{- if $name -}}
{{- $components = append $components (printf "worker-%s" $name) -}}
{{- end -}}
{{- end -}}
{{- range $kind := list "postgres" "qdrant" "objects" "neo4j" -}}
{{- $components = append $components (printf "backup-%s" $kind) -}}
{{- end -}}
{{- $components | toJson -}}
{{- end -}}

{{/* PromQL label matchers for autoscaling queries. */}}
{{- define "rudix.c1.promMatchers" -}}
{{- $configured := .Values.autoscaling.prometheus.labelMatchers | default "" | toString -}}
{{- if $configured -}}
{{- $configured -}}
{{- else -}}
{{- printf "namespace=%q" .Release.Namespace -}}
{{- end -}}
{{- end -}}

{{/* ClusterIP Service: (dict "root" $ "component" <name> "port" <int> "portName" <name>). */}}
{{- define "rudix.c1.service" -}}
{{- $ctx := dict "root" .root "component" .component -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "rudix.componentName" $ctx }}
  labels:
    {{- include "rudix.labels" $ctx | nindent 4 }}
spec:
  type: ClusterIP
  selector:
    {{- include "rudix.selectorLabels" $ctx | nindent 4 }}
  ports:
    - name: {{ .portName }}
      port: {{ int .port }}
      targetPort: {{ .portName }}
      protocol: TCP
{{- end -}}

{{/* PodDisruptionBudget allowing podDisruptionBudget.maxUnavailable evictions at a time. */}}
{{- define "rudix.c1.pdb" -}}
{{- $ctx := dict "root" .root "component" .component -}}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "rudix.componentName" $ctx }}
  labels:
    {{- include "rudix.labels" $ctx | nindent 4 }}
spec:
  maxUnavailable: {{ .root.Values.podDisruptionBudget.maxUnavailable }}
  selector:
    matchLabels:
      {{- include "rudix.selectorLabels" $ctx | nindent 6 }}
{{- end -}}

{{/* Labels selecting every pod of the release. */}}
{{- define "rudix.c1.releaseSelector" -}}
app.kubernetes.io/name: {{ include "rudix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Standard labels for a NetworkPolicy, which spans components: (dict "root" $ "name" <n>). */}}
{{- define "rudix.c1.policyLabels" -}}
helm.sh/chart: {{ include "rudix.chart" .root }}
{{ include "rudix.c1.releaseSelector" .root }}
app.kubernetes.io/component: networkpolicy
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
app.kubernetes.io/part-of: rudix
{{- end -}}

{{/* <fullname>-<suffix> for a NetworkPolicy name, at most 63 characters. */}}
{{- define "rudix.c1.policyName" -}}
{{- printf "%s-%s" (include "rudix.fullname" .root) .name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* HPA behavior: fast scale-up, slow and stabilized scale-down (seconds as argument). */}}
{{- define "rudix.c1.hpaBehavior" -}}
scaleUp:
  stabilizationWindowSeconds: 0
  policies:
    - type: Percent
      value: 100
      periodSeconds: 60
scaleDown:
  stabilizationWindowSeconds: {{ int . }}
  policies:
    - type: Pods
      value: 1
      periodSeconds: 60
{{- end -}}

{{/* CPU and memory utilization metrics for an autoscaling/v2 HPA. */}}
{{- define "rudix.c1.resourceMetrics" -}}
- type: Resource
  resource:
    name: cpu
    target:
      type: Utilization
      averageUtilization: {{ int .targetCPUUtilizationPercentage }}
- type: Resource
  resource:
    name: memory
    target:
      type: Utilization
      averageUtilization: {{ int .targetMemoryUtilizationPercentage }}
{{- end -}}

{{/* KEDA cpu and memory triggers (Utilization). */}}
{{- define "rudix.c1.resourceTriggers" -}}
- type: cpu
  metricType: Utilization
  metadata:
    value: {{ int .targetCPUUtilizationPercentage | quote }}
- type: memory
  metricType: Utilization
  metadata:
    value: {{ int .targetMemoryUtilizationPercentage | quote }}
{{- end -}}

{{/* A PromQL regex matching exactly the given queue names (dots escaped). */}}
{{- define "rudix.c1.queueRegex" -}}
{{- $escaped := list -}}
{{- range . -}}
{{- $escaped = append $escaped (regexQuoteMeta (toString .) | replace "\\" "\\\\") -}}
{{- end -}}
{{- $escaped | join "|" -}}
{{- end -}}
