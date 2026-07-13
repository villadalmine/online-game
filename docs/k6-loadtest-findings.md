# K6 Load Testing en DT: Findings & Backlog

**Fecha:** 2026-07-13
**Autor:** Antigravity (IA) / Preparado para Claude

## 1. Contexto y Qué se hizo
Se ejecutó el pipeline de pruebas de carga (`deploy/build/online-game-loadtest.yaml`) el cual despliega el entorno efímero `galaxy-dt` en el namespace `online-game-dt` y ejecuta un script de k6 (`tests/load/k6_ccu.js`) simulando 100 usuarios concurrentes (VUs).

**Acciones realizadas:**
1. Se corrigió un problema de RBAC en `online-game-loadtest.yaml` (se eliminó `--create-namespace` del comando `helm upgrade` ya que el ServiceAccount de ArgoCD no tenía permisos a nivel cluster).
2. Se corrigió la regla `nodeSelector` en `values-dt.yaml` que bloqueaba los pods en estado `Pending` por un match imposible de hostname.
3. Se actualizó el password en el script de k6 (`tests/load/k6_ccu.js`), pasando de `"x"` a `"password123"`, debido a que las nuevas políticas de seguridad de la API devuelven HTTP 422 si la contraseña tiene menos de 6 caracteres.

## 2. Resultados de la Ejecución (Qué se encontró mal)
El test logró ejecutar el tráfico correctamente, comprobando que la lógica del script de k6 y los endpoints funcionan. Sin embargo, **el pipeline falla (exit status 99) porque se rompen los umbrales (Thresholds) de rendimiento configurados en K6**.

**Output y Métricas Clave:**
- **Tasa de éxito de requests:** ~90%
- **Tasa de fallo (`http_req_failed`):** 9.84% (El umbral exige < 1%)
- **Latencia de `/players/me` (`me_latency`):** P95 = 10 segundos (El umbral exige < 200ms)

## 3. Diagnóstico
Bajo una carga de 100 VUs paralelos ejecutando registro, onboarding y ping continuo:
- La infraestructura actual del entorno DT (`cpu: 1`, `memory: 512Mi` por default, sumado a una BD PostgreSQL efímera) **se satura**.
- Esto provoca que ~10% de las peticiones sean rechazadas por el servidor (probablemente timeouts o encolamiento en Uvicorn/PostgreSQL) y que los tiempos de respuesta se disparen a 10 segundos.

## 4. Next Steps para Claude (Backlog)
Para lograr que el pipeline de Load Test pase exitosamente, se deben tomar decisiones sobre la infraestructura o sobre los umbrales:

1. **Opción A (Ajuste de Infraestructura):** Asignar mayores límites de CPU/Memoria al deployment de `galaxy-dt` y a la base de datos efímera en `values-dt.yaml` para soportar 100 VUs reales sin latencia. Investigar si es Uvicorn o la BD el cuello de botella exacto.
2. **Opción B (Ajuste de Expectativas):** Si 100 VUs es un pico extremo que no esperamos manejar con la configuración DT actual, relajar los thresholds en `tests/load/k6_ccu.js` o reducir la cantidad de VUs del test para que sirva como validación funcional bajo estrés moderado, en lugar de estrés extremo.
