# Load test (SDD 7 §5)

Reproduce el mix real de un **usuario concurrente (CCU)** para medir `rps_por_pod` y validar
el autoscaling. **No corre en CI** (cuesta tiempo/recursos): se ejecuta a mano contra un
deploy real (1 pod con requests/limits fijos para calibrar, luego escalando réplicas).

## Modelo de carga (por CCU)

| Llamada | Frecuencia | rps |
|---|---|---|
| SSE poll (`STREAM_INTERVAL`) | 1 / 2 s | 0.50 |
| `GET /players/me` (incluye `advance`, la lectura cara) | 1 / 4 s | 0.25 |
| Acciones (build/train/attack/advisor) | ráfagas | ~0.05 |
| **Total** | | **~0.8 rps/CCU** |

Subir `STREAM_INTERVAL` a 5 s ⇒ ~0.45 rps/CCU. Luego:
`CCU_max ≈ (rps_por_pod × n_pods) / rps_por_CCU`, con `rps_por_pod` medido acá (no inventado),
y recordando que **Postgres es el techo** (`pool_size × n_pods ≤ max_connections` → PgBouncer).

## Correr

```sh
# k6: https://k6.io
BASE_URL=https://tu-deploy/api/v1 VUS=200 DURATION=3m k6 run tests/load/k6_ccu.js
```

Reportá p50/p95/p99 de `/players/me`, rps por pod, CPU/mem por pod, conexiones Postgres y
duración del tick. **Criterio de aceptación**: a `maxReplicas`, p95 `/players/me` < objetivo
(p.ej. 200 ms) y conexiones DB < límite.
