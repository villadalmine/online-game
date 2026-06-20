{{- define "online-game.dbUrl" -}}
postgresql+asyncpg://{{ .Values.postgres.user }}:{{ .Values.postgres.password }}@{{ .Release.Name }}-postgres:5432/{{ .Values.postgres.db }}
{{- end -}}

{{- define "online-game.redisUrl" -}}
redis://{{ .Release.Name }}-redis:6379/0
{{- end -}}

{{- define "online-game.commonEnv" -}}
- name: DATABASE_URL
  value: {{ include "online-game.dbUrl" . | quote }}
- name: REDIS_URL
  value: {{ include "online-game.redisUrl" . | quote }}
{{- range $k, $v := .Values.env }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end -}}
