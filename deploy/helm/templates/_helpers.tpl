{{- define "online-game.dbUrl" -}}
postgresql+asyncpg://{{ .Values.postgres.user }}:{{ .Values.postgres.password }}@{{ .Release.Name }}-postgres:5432/{{ .Values.postgres.db }}
{{- end -}}

{{- define "online-game.redisUrl" -}}
redis://{{ .Release.Name }}-redis:6379/0
{{- end -}}

{{- define "online-game.imagePullSecrets" -}}
{{- if .Values.imagePullSecrets }}
imagePullSecrets:
{{- range .Values.imagePullSecrets }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "online-game.commonEnv" -}}
- name: DATABASE_URL
  value: {{ include "online-game.dbUrl" . | quote }}
- name: REDIS_URL
  value: {{ include "online-game.redisUrl" . | quote }}
- name: NPC_BRAIN
  value: {{ .Values.npc.brain | quote }}
- name: OPENROUTER_BASE_URL
  value: {{ .Values.openrouter.baseUrl | quote }}
- name: OPENROUTER_MODEL
  value: {{ .Values.openrouter.model | quote }}
{{- if .Values.openrouter.apiKey }}
- name: OPENROUTER_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Release.Name }}-secrets
      key: OPENROUTER_API_KEY
{{- end }}
{{- range $k, $v := .Values.env }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end -}}
