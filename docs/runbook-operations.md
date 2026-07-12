# Runbook de Operaciones: Pruebas de Carga y Gestión de Temporadas

Este documento detalla los procedimientos operativos para correr pruebas de estrés en el clúster sin afectar producción, y cómo gestionar el reinicio de las temporadas (DB wipe) para lanzamientos limpios.

## 1. Pruebas de Carga (Stress Testing) con Argo Workflows

Para probar si el servidor resiste la concurrencia de jugadores usando inteligencia artificial, hemos diseñado un entorno efímero (`galaxy-dt`) que se levanta, recibe tráfico simulado, y se destruye automáticamente.

### Requisitos Previos
* Debes tener acceso al clúster vía `kubectl` y `argo`.
* Necesitas tu API Key de OpenRouter, ya que la simulación usará el modelo barato (`meta-llama/llama-3.1-8b-instruct`) configurado en `values-dt.yaml`.

### Cómo ejecutar la prueba
Ejecuta el workflow pasándole tu clave de OpenRouter y ajustando la cantidad de usuarios (`vus`) o la duración (`duration`) si lo deseas:

```bash
argo submit deploy/build/online-game-loadtest.yaml -n kaniko \
  -p openrouter_key="sk-or-v1-tu-clave-aqui" \
  -p vus=100 \
  -p duration=3m \
  --watch
```

### Qué sucede por detrás:
1. **helm-setup:** Se despliega el juego en el namespace `online-game-dt` inyectándole tu API key.
2. **k6-test:** Lanza un pod con `grafana/k6` que ejecuta `tests/load/k6_ccu.js`, bombardeando el entorno de prueba con registros, onboarding y peticiones al Assistant.
3. **helm-teardown:** Sin importar el resultado de la prueba, Argo limpiará y borrará el namespace `online-game-dt`. Cero basura en el clúster.

---

## 2. Lanzamiento del Juego (Hard Reset y Temporadas)

### Ciclo de vida natural (Automático)
Una vez que el juego está lanzado, **no debes hacer nada para pasar de una temporada a otra**. El proceso `worker.py` detecta si la temporada expiró, hace un snapshot del Hall of Fame, resetea los puntos y abre la siguiente temporada. El imperio del jugador (planetas, edificios) **se mantiene intacto**.

### Hard Reset (Día de Lanzamiento o Wipe Total)
Para el Día 0 (lanzamiento oficial al público), querrás borrar todas las bases de datos de prueba. Dado que usamos Postgres persistente en Producción, un reinicio total implica borrar los datos del volumen persistente.

Para hacerlo limpiamente desde Argo/Helm:
1. Desinstala la release actual para bajar los pods que bloquean la base de datos:
   ```bash
   helm uninstall galaxy -n online-game
   ```
2. Borra los PersistentVolumeClaims (PVC) de la base de datos (Postgres) y Redis para destruir los datos físicos:
   ```bash
   kubectl delete pvc data-galaxy-postgresql-0 -n online-game
   kubectl delete pvc redis-data-galaxy-redis-master-0 -n online-game
   ```
3. Re-despliega usando tu pipeline estándar:
   ```bash
   make deploy V=1.0.0
   ```
Al levantar, Helm recreará volúmenes limpios, Alembic correrá las migraciones automáticamente desde cero, y tendrás una base de datos 100% virgen lista para que se registren los primeros 100 usuarios.
