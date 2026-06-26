# SDD 44 — CD de un paso: build + deploy in-cluster (Argo Workflow)

> **Estado:** **diseño + implementado (manifiestos)** · **Fecha:** 2026-06-26 · **Autor:** equipo online-game
> **Relacionado:** [SDD 15 build Kaniko](sdd-image-build-kaniko.md),
> [SDD 17 runbook deploy](sdd-deploy-upgrade.md), [SDD 16 migraciones](sdd-migrations-deploy.md),
> `deploy/build/online-game-cicd.yaml`, `deploy/build/cicd-rbac.yaml`, `deploy/helm`.

## 1. Objetivo

Hoy el deploy son **dos pasos**: el Argo Workflow **buildea** (Kaniko, SDD 15) y después uno corre
`helm upgrade` **a mano** (SDD 17). Queremos que el Workflow haga **build _y_ deploy en una sola
corrida** (CD in-cluster), para no depender del paso manual ni de tener `helm` + el kubeconfig en la
laptop. El `helm upgrade` manual queda como **fallback documentado** (cambios de chart/values).

## 2. No-objetivos
- **No** es GitOps completo (ArgoCD/Flux con reconciliación continua): es un Workflow imperativo que
  se dispara por release, igual que hoy.
- **No** cambia migraciones: siguen corriendo en el initContainer `migrate` (SDD 16) en cada rollout.
- **No** mueve secretos/values al repo: el deploy **reutiliza** los values del release vivo.

## 3. Diseño

### 3.1 Un Workflow, dos pasos (DAG)
`deploy/build/online-game-cicd.yaml` reemplaza el de build-only para el camino feliz: un DAG
`build → deploy`. El **tag** de imagen es un **parámetro** del Workflow (`image_tag`), usado tanto en
el `--destination` de Kaniko como en el `--set image.tag` de helm — así **no se edita el YAML** por
release (era un paso a mano frágil).

```
arguments.parameters: [ image_tag ]
  build  (kaniko)  --destination=...:{{workflow.parameters.image_tag}}
  deploy (helm)    depende de build; helm upgrade ... --set image.tag={{...}}
```

Ambos pods comparten el **PVC workspace** (RWO, mismo nodo via `nodeSelector`) → el clone de git que
hace el step de build queda disponible para el de deploy (que necesita el **chart** `deploy/helm`).

### 3.2 Deploy sin tocar secretos: `--reuse-values`
El clone viene de GitHub (repo público) y **NO trae `values-local.yaml`** (gitignored: dominio, IPs,
`JWT_SECRET`, key de OpenRouter). Por eso el step de deploy hace:

```sh
helm upgrade galaxy /workspace/source/deploy/helm -n online-game \
  --reuse-values --set image.tag={{workflow.parameters.image_tag}} \
  --wait --timeout 5m
```

`--reuse-values` **reutiliza los values del release vivo** (los que se setearon en el último deploy:
dominio, secrets, key de OpenRouter) y solo **pisa `image.tag`**. Resultado: el Workflow **nunca ve
ni necesita** los secretos. Imagen del step: `dtzar/helm-kubectl` (multi-arch, trae helm+kubectl).

> **Límite conocido:** `--reuse-values` **no** incorpora *defaults nuevos* de un chart cambiado. Si
> una release agrega/renombra values o templates que necesitan un valor nuevo → usar el **fallback
> manual** (`helm upgrade -f deploy/helm/values-local.yaml …`, SDD 17). El camino in-cluster es para
> **bumps de imagen** (el caso del 99% de las releases).

### 3.3 RBAC mínima (`deploy/build/cicd-rbac.yaml`)
El Workflow corre en ns `kaniko`; el deploy actúa sobre ns `online-game`. Creamos:
- **ServiceAccount** `og-deployer` en `kaniko` (el Workflow corre con este SA).
- **Role** `og-deployer` en `online-game` con permisos que helm necesita para el chart: `get/list/
  watch/create/update/patch/delete` sobre `deployments`, `statefulsets`, `services`, `configmaps`,
  `secrets` (helm guarda el estado del release como Secret), `serviceaccounts`, `pods`, `jobs`,
  `cronjobs`, `persistentvolumeclaims`, y `httproutes`/`gateways` (gateway-api) si el chart los toca.
  **RoleBinding** liga ese Role al SA `og-deployer` de `kaniko` (binding cross-namespace).
- **Role** `og-deployer-executor` en `kaniko` con los permisos del executor de Argo
  (`pods`, `pods/log`, `workflowtaskresults` create/patch) + RoleBinding al SA.

Es **namespaced y de mínimo privilegio**: nada de `cluster-admin`. Si el chart incorpora un tipo de
recurso nuevo, se agrega ese verbo/recurso al Role.

### 3.4 Disparo
```sh
# con argo CLI (recomendado): pasa el tag por parámetro, no edita YAML
argo submit deploy/build/online-game-cicd.yaml -n kaniko -p image_tag=<X.Y.Z> --watch
# o, si no hay argo CLI, kubectl create (usa el default del YAML — editar image_tag default):
kubectl create -f deploy/build/online-game-cicd.yaml
```
Un target `make deploy V=X.Y.Z` lo envuelve (intenta `argo submit -p`, cae a `kubectl create`).

## 4. Seguridad
- SA con **permisos namespaced mínimos**; sin acceso fuera de `online-game`/`kaniko`.
- **Secretos nunca en git**: `--reuse-values` evita pasar values/keys por el Workflow; la key de
  OpenRouter persiste en el release (Secret en `online-game`).
- El registry interno sigue HTTP in-cluster (`--insecure`), igual que SDD 15.

## 5. Riesgos / decisiones
- **`--reuse-values` vs chart nuevo:** documentado el fallback manual (§3.2).
- **PVC RWO compartido:** build y deploy van al **mismo nodo** (`nodeSelector`) y son **secuenciales**
  (DAG) → RWO alcanza.
- **Rollback:** `helm rollback galaxy <REV>` (datos intactos, PVC) — igual que SDD 17 §6.
- **Migraciones:** sin cambios; corren en el initContainer en el rollout que dispara el deploy.

## 6. Verificación (e2e de infra)
1. `argo submit … -p image_tag=<tag> --watch` → Workflow `Succeeded` (build + deploy).
2. `kubectl get deploy galaxy-api -n online-game -o jsonpath='{...image}'` == el tag nuevo.
3. `kubectl rollout status deploy/galaxy-api -n online-game` OK; `/health` responde.
4. Si el deploy falla (RBAC, values), el Workflow queda `Failed` con el log del step `deploy` →
   se diagnostica sin tocar prod, y el release anterior sigue vivo (helm no promovió).

## 7. Estado / fallback
El **build-only** (`deploy/build/online-game-kaniko.yaml`, SDD 15) se conserva como fallback para
cuando se quiera buildear sin desplegar, o para el camino manual de SDD 17 ante cambios de chart.
