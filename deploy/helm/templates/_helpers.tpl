{{- define "online-game.dbUrl" -}}
{{- if .Values.postgres.externalUrl -}}
{{ .Values.postgres.externalUrl }}
{{- else -}}
postgresql+asyncpg://{{ .Values.postgres.user }}:{{ .Values.postgres.password }}@{{ .Release.Name }}-postgres:5432/{{ .Values.postgres.db }}
{{- end -}}
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
{{- if .Values.llm.baseUrl }}
- name: LLM_BASE_URL
  value: {{ .Values.llm.baseUrl | quote }}
{{- end }}
{{- if .Values.llm.model }}
- name: LLM_MODEL
  value: {{ .Values.llm.model | quote }}
{{- end }}
{{- if .Values.llm.jsonMode }}
- name: LLM_JSON_MODE
  value: {{ .Values.llm.jsonMode | quote }}
{{- end }}
{{- if .Values.llm.timeoutSeconds }}
- name: LLM_TIMEOUT_SECONDS
  value: {{ .Values.llm.timeoutSeconds | quote }}
{{- end }}
{{- if .Values.mail }}
{{- if .Values.mail.backend }}
- name: MAIL_BACKEND
  value: {{ .Values.mail.backend | quote }}
{{- end }}
{{- if .Values.mail.from }}
- name: MAIL_FROM
  value: {{ .Values.mail.from | quote }}
{{- end }}
{{- if .Values.mail.resendApiKey }}
- name: RESEND_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Release.Name }}-secrets
      key: RESEND_API_KEY
{{- end }}
{{- if .Values.mail.otpSecret }}
- name: OTP_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ .Release.Name }}-secrets
      key: OTP_SECRET
{{- end }}
{{- end }}
{{- if .Values.scaling }}
{{- if .Values.scaling.streamInterval }}
- name: STREAM_INTERVAL
  value: {{ .Values.scaling.streamInterval | quote }}
{{- end }}
{{- if .Values.scaling.dbPoolSize }}
- name: DB_POOL_SIZE
  value: {{ .Values.scaling.dbPoolSize | quote }}
{{- end }}
{{- if .Values.scaling.dbMaxOverflow }}
- name: DB_MAX_OVERFLOW
  value: {{ .Values.scaling.dbMaxOverflow | quote }}
{{- end }}
{{- end }}
{{- if .Values.llm.apiKey }}
- name: LLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Release.Name }}-secrets
      key: LLM_API_KEY
{{- end }}
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
