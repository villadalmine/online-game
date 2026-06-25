# SDD 30 — Mantenimiento y resiliencia: apagar el fierro GPU (`srv-t7910`)

> **Estado:** **pendiente** (infra/ops) · **Fecha:** 2026-06-24
> **Relacionado:** [SDD 9 LLM/GPU + fallback](sdd-local-gpu-llm.md), [SDD 10 durabilidad/backup](sdd-durability-backup-restore.md),
> [SDD 28 métricas LLM/GPU](sdd-llm-usage-metrics.md), [SDD 7 capacidad](sdd-capacity-autoscaling.md),
> `deploy/helm/templates/datastores.yaml`, `deploy/helm/values.yaml` (`postgres.persistence`).

## 1. Objetivo
Poder **apagar el nodo físico `srv-t7910`** (el amd64 con las 2 GPUs) para mantenimiento, sabiendo
**qué impacto tiene**, cómo la **IA cae sola a OpenRouter free**, y **qué pasa con el storage** (ese
fierro **no es nodo de storage**: usa `local-path` node-local).

## 2. Qué corre HOY en `srv-t7910` (verificado 2026-06-24)
- **IA/GPU del juego:** `ollama-a` (Tesla P4) + `ollama-b` (Quadro M4000) + `dcgm-exporter`.
- **DB del juego (CRÍTICO):** `galaxy-postgres-0` con PVC `data-galaxy-postgres-0` en **`local-path`**
  (node-local, fijado a srv-t7910).
- **Plataforma (ajeno al juego):** vclusters, KubeVirt/CAPI, longhorn-manager, etc.
- **NO acá:** el **registry** (en RK1) y los **builds Kaniko** (en RK1) → el build/deploy no se afecta.

## 3. Impacto al apagarlo (por componente)
| Componente | Qué pasa | ¿Bloquea el juego? |
|---|---|---|
| **IA / LLM (ollama-a/b)** | backends `local-gpu` caen → LiteLLM **rutea a OpenRouter free**; el juego cae a reglas/determinista | **No** — degrada (IA vía nube) |
| **DB Postgres (local-path)** | **no puede reagendar** (volumen node-local) → **juego caído** hasta que vuelva el nodo | **SÍ** — es el punto crítico |
| **DCGM / HAMI métricas GPU** | dejan de reportar | No (sólo observabilidad) |
| **Build (Kaniko) / registry** | en RK1 → intactos | No |
| **API / Redis del juego** | en `srv-super6c-*` → intactos (si Postgres estuviera HA) | — |

**Conclusión:** lo que NO molesta es la GPU (tiene fallback). **Lo que tira el juego es el Postgres
en `local-path` sobre el fierro que apagás.**

## 3.bis Blast-radius COMPLETO de apagar `srv-t7910` (no sólo el juego)
`srv-t7910` no sólo hostea la IA y la DB del juego — corre **mucha plataforma**. Verificado
2026-06-24 (`kubectl get pods -A --field-selector spec.nodeName=srv-t7910`):

| Componente | Impacto al apagar | Severidad |
|---|---|---|
| **Juego: Postgres** | con el fix (SDD 32: Longhorn + `nodeSelector`) **reagenda a un RK1 (~40 s)** | ✅ resuelto |
| **Juego: IA (ollama-a/b, dcgm)** | caen → LiteLLM → OpenRouter free | ✅ degradado |
| **KubeVirt VMs** (`virt-launcher-*`: host-euw1/host-mgmt/mgmt-child control-plane+md) | esas **VMs mueren** → nodos/control-planes de tus clústers anidados (CAPI) caen | 🔴 **alto** (plataforma) |
| **vcluster-tenant-a-\*** (acceptance/dev/prod: vcluster-0, tenant-postgres-0, coredns, external-secrets) | el **control-plane del tenant-a** y su Postgres en este nodo caen | 🔴 alto (tenant) |
| **Longhorn** (instance-manager/csi/engine en srv-t7910) | volúmenes con réplica acá quedan **degraded** y rebuildan en otros nodos (dato a salvo si réplica ≥2) | 🟠 medio |
| **HAMI** (device-plugin/scheduler) | scheduling de GPU del cluster se rehace al reagendar el scheduler | 🟠 medio |
| **capi-controller-manager** | si es la única réplica, CAPI pausa reconciliación hasta reagendar | 🟠 medio |
| **monitoring** (node-exporter/alloy/loki-canary) | se pierden métricas/logs **de ese nodo** | 🟢 bajo |
| Cilium agent/envoy (DaemonSet) | ese nodo pierde red (esperado, está apagado) | 🟢 bajo |

**Conclusión:** para el **juego** ya es seguro (Postgres reagenda, IA a nube). El **verdadero
blast-radius está en la PLATAFORMA**: `srv-t7910` corre **VMs de KubeVirt que son control-planes de
clústers anidados (CAPI) y vclusters de tenants**. Apagarlo planificado debería **drenar/migrar esas
VMs primero** (KubeVirt live-migration o apagar los tenants) — fuera del alcance del juego, pero a
tener en cuenta antes de cortar la corriente.

## 4. Cómo la app/LLM hace fallback "todo a OpenRouter free" (ya implementado)
Cadena de detección → fallback (SDD 9/28):
1. **LiteLLM** detecta el backend caído: `request_timeout`/`timeout` por modelo + `allowed_fails`/
   `cooldown_time` (router) → marca `local-gpu` en cooldown → enruta a la **cadena de fallback**
   `local-gpu → llama70b-free → kimi-free → paid-final` (modelos OpenRouter free).
2. **El juego** además tiene su propio fallback (SDD 9): `llm_timeout_seconds` corta la espera →
   NPC → reglas; asistente → determinista. Nunca rompe el turno/responde vacío.
→ Apagar la GPU = la IA **sigue andando vía OpenRouter free**, sin tocar nada (ya configurado).
**Importante:** el **DB NO tiene fallback** (no es un LLM). Su resiliencia es **storage replicado o
backup/restore** (§5/§6), no un fallback de la app.

## 5. Storage — el punto a arreglar ("en el fierro no corro storage")
`srv-t7910` usa **`local-path`** (default) para lo que cayó ahí:
- **PVC de ollama (modelos):** `local-path` → es un **cache re-descargable**; al volver el nodo,
  Ollama re-baja el modelo. **Aceptable.**
- **PVC de Postgres (`data-galaxy-postgres-0`):** `local-path` node-local → **el problema**. Apagar el
  nodo = DB indisponible; si el **disco muere**, se pierde sin backup.

**Recomendación (fix clave):** mover el Postgres del juego a **Longhorn** (replicado en los nodos de
storage RK1) → el volumen sobrevive la caída del fierro y **Postgres reagenda a otro nodo**:
```yaml
# values-local.yaml
postgres:
  persistence:
    storageClass: longhorn        # (o longhorn-nvme) en vez de "" (local-path)
```
> El `storageClass` de un PVC ya creado es **inmutable** → migrar = **backup (pg_dump, SDD 10) →
> recrear el StatefulSet/PVC con `longhorn` → restore**. Hacerlo en una ventana corta (ver §6).
> Alternativas: **DB externa/managed** (`postgres.enabled=false` + `externalUrl`, SDD 10) o no fijar
> Postgres a srv-t7910.

## 5.bis Dos niveles de "replicación" de Postgres (no confundir)
Estado: **no hay operador de Postgres** en el cluster — juego/tenants/leloir son StatefulSets de 1
instancia. Para sobrevivir la caída de un nodo hay dos caminos:

| | **A — Storage replicado (Longhorn)** | **B — HA Postgres (operador CNPG)** |
|---|---|---|
| Qué replica | el **volumen** (3 réplicas en RK1) | **el Postgres**: primary + standby(s) con streaming replication |
| Caída de nodo | el pod **reagenda** y reengancha el volumen | **failover automático** a un standby |
| Downtime | ~1-3 min (reschedule + restart) | ~segundos |
| Complejidad | mínima (1 línea `storageClass`) | operador + CR `Cluster` |
| Extra | — | **backups/PITR a object storage** incluidos (cierra follow-up SDD 10) |
| App | `postgres.persistence.storageClass: longhorn` | `postgres.enabled=false` + `externalUrl` al Service del Cluster CNPG |

**Recomendación:** para esta escala (DB chica, juego por turnos) **A (Longhorn) alcanza** y es lo más
simple. Si se quiere **HA real** (failover en segundos) y/o **estandarizar Postgres + backups/PITR** en
todo el homelab (tenants, leloir, juego), instalar **CloudNativePG** y apuntar el juego por
`externalUrl` (sin tocar código). CNPG es el estándar k8s-native moderno (mejor que Zalando/Bitnami HA
para la mayoría de los casos).

## 6. Runbook de apagado planificado de `srv-t7910`
**Pre-requisito recomendado:** Postgres en Longhorn (§5). Si sigue en `local-path`, el apagado
implica **downtime del juego** (la DB no se mueve) → avisar/ventana.

1. **Backup** (siempre): `pg_dump` del juego (CronJob de backup de SDD 10, o manual).
2. **Cordon:** `kubectl cordon srv-t7910` (no agenda nada nuevo ahí).
3. **Drain:** `kubectl drain srv-t7910 --ignore-daemonsets --delete-emptydir-data`
   - `ollama-a/b` + `dcgm` se desalojan → quedan **Pending** (pinneados a la GPU por `use-gputype`) →
     la **IA sigue por OpenRouter free** mientras tanto.
   - **Postgres en Longhorn** → reagenda a otro nodo (volumen replicado) → **juego sigue**.
   - **Postgres en local-path** → drain **no puede moverlo** (lo salta o lo borra) → **DB down**:
     hacerlo sólo en ventana, con backup, y levantar el nodo lo antes posible.
   - DaemonSets (Cilium, longhorn-csi, hami, node-exporter) **se quedan** (`--ignore-daemonsets`).
4. **Apagar el fierro.**
5. **Al volver:** encender → `kubectl uncordon srv-t7910` → `ollama-a/b`+`dcgm` reagendan; LiteLLM
   vuelve a usar `local-gpu` (cuando el modelo recarga; cold-start ~1ª llamada). La IA vuelve a la GPU.

## 7. Tabla "qué sobrevive al apagar el fierro"
| | HOY (local-path) | Con el fix (Longhorn) |
|---|---|---|
| IA del juego | ✅ sigue (OpenRouter free) | ✅ sigue (OpenRouter free) |
| DB / juego jugable | ❌ caído hasta que vuelva el nodo | ✅ reagenda a otro nodo |
| Datos del juego | ⚠️ a salvo si apagado limpio; en riesgo si muere el disco | ✅ replicado (sobrevive pérdida de 1 nodo) |
| Builds / deploy | ✅ (RK1) | ✅ |

## 8. Recomendaciones / decisiones
- **Acción #1 (alto impacto):** Postgres del juego → **Longhorn** (o DB externa). Es lo que convierte
  "apagar el fierro = juego caído" en "apagar el fierro = sólo la IA degrada a nube".
- **GPU = recurso best-effort** con fallback (ya está) → apagarla nunca debe tirar el juego.
- **Backups offsite + PITR** (follow-up de SDD 10) para el caso de pérdida total del disco.
- **Alerta** (opcional): `KubeNodeNotReady`/`up{node=srv-t7910}` → Telegram, para saber cuándo el
  fierro se cae (planeado o no).

## 9. Validación / tests
- **Drill (staging):** con Postgres en Longhorn, `drain srv-t7910` → verificar que Postgres reagenda
  y el juego responde, y que la IA cae a OpenRouter free (panel "GPU vs nube", SDD 28).
- **Servicio (ya cubierto):** el LLM caído → el juego no rompe (NPC→reglas, asistente→determinista;
  tests de SDD 9). LiteLLM fallback a free (config SDD 9).
- **Restore drill:** `pg_dump` → restore en un PVC Longhorn nuevo (SDD 10).
