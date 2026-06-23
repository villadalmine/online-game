# SDD 17 — Runbook de deploy / upgrade (de código nuevo a producción)

> **Estado:** implementado · **Fecha:** 2026-06-23 · **Autor:** equipo online-game
> **Relacionado:** [SDD 15 build Kaniko](sdd-image-build-kaniko.md),
> [SDD 16 migraciones](sdd-migrations-deploy.md), [SDD 10 durabilidad](sdd-durability-backup-restore.md),
> `deploy/helm`, `deploy/build/online-game-kaniko.yaml`.

## 1. Objetivo

El paso a paso para llevar **código nuevo de `main` a producción** sin perder datos: build de imagen
→ `helm upgrade` → migraciones automáticas → verificación. Reproducible y seguro.

## 2. Pre-requisitos (ya en pie, una sola vez)

- Cluster con el release **`galaxy`** en ns `online-game` (chart `deploy/helm`).
- Build in-cluster: ns `kaniko` + Argo Workflows (SDD 15). Registry interno `registry.registry:5000`.
- TLS público: cert-manager + ClusterIssuers + secret `acme-dns-account` + el **listener HTTPS** del
  dominio en el Gateway (SDD deploy/gateway-tls). Postgres con PVC (SDD 10).
- **Values reales** en un archivo gitignored (dominio, IPs, emails, `JWT_SECRET`). La key de
  OpenRouter se pasa por `--set` desde `.env` (no se imprime).

## 3. Upgrade rutinario (código nuevo)

```sh
# 1) Código a main (Kaniko clona de GitHub, no del disco)
git push origin main

# 2) Subir el tag en deploy/build/online-game-kaniko.yaml (--destination=...:<NUEVO_TAG>) y buildear
kubectl create -f deploy/build/online-game-kaniko.yaml
kubectl wait workflow -l app=online-game-build -n kaniko \
  --for=jsonpath='{.status.phase}'=Succeeded --timeout=900s

# 3) Desplegar la imagen nueva (values reales gitignored; key OpenRouter desde .env)
OR_KEY=$(grep '^OPENROUTER_API_KEY=' .env | cut -d= -f2-)
helm upgrade galaxy deploy/helm -n online-game \
  -f deploy/helm/values-<tuyo>.yaml \
  --set image.tag=<NUEVO_TAG> \
  --set openrouter.apiKey="$OR_KEY"

# 4) Verificar el rollout + migraciones
kubectl rollout status deploy/galaxy-api -n online-game --timeout=180s
kubectl logs deploy/galaxy-api -n online-game -c migrate --tail=20   # aplicó / no-op
```

**Qué pasa con la DB** (detalle en SDD 16): el initContainer `migrate` corre `alembic upgrade head`
antes de servir. Si hubo cambios de modelo (y commiteaste la migración) → aplica solo lo pendiente,
**sin borrar datos**. Si no hubo → **no-op**. El PVC de Postgres persiste (SDD 10).

## 4. Verificación post-deploy (smoke)

```sh
R="--resolve <HOST>:443:<IP-GATEWAY>"; B="https://<HOST>/api/v1"
curl -s $R https://<HOST>/health                                   # {"status":"ok",...}
curl -s $R -X POST $B/auth/request-code -d '{"email":"x@x.com"}' -H 'Content-Type: application/json' -w " %{http_code}\n"
curl -s $R -X POST $B/players/me/advisor/ask -d '{"message":"hi"}' -H 'Content-Type: application/json' -w " %{http_code}\n"  # 401 = existe
```
Cert público válido: `curl` **sin `-k`** debe dar `verify=0` (emisor Let's Encrypt, no STAGING).

## 5. Casos especiales

- **Cambió el esquema**: `make migration m="…"` + revisar + `make test` (incluye `test_migrations`)
  ANTES de buildear; la migración viaja en la imagen (SDD 16 §3A). Migraciones **expand/contract**
  (compatibles hacia atrás) para no romper durante el rolling update.
- **Solo cambió config/env** (no código): no hace falta rebuild; `helm upgrade` con los values
  nuevos (p.ej. cambiar `ALLOWED_EMAILS`) rola los pods. *Nota:* si la feature es de código nuevo
  (gate de allowlist, OTP, asistente), NO alcanza con la env — necesita la imagen que la trae.
- **Flip de cert staging→prod**: `--set gateway.tls.issuer=letsencrypt-prod`; cert-manager reemite
  en el mismo secret y el listener lo toma solo.
- **Allowlist**: `ALLOWED_EMAILS` (coma-separado) en los values; vacío = registro abierto. Cambiarla
  = `helm upgrade` (rola pods). Solo aplica con imagen que tenga SDD 14.

## 6. Rollback

- Imagen: `helm rollback galaxy <REV>` o `--set image.tag=<TAG_ANTERIOR>`. **Datos intactos** (PVC).
- Esquema: Alembic no hace downgrade solo; por eso migraciones expand/contract (SDD 16 §5). Backup
  antes de releases grandes (SDD 10).

## 7. Estado actual (referencia)

Producción corre el release `galaxy` (ns `online-game`), reusando el `cluster-gateway` compartido
(`gateway.create=false`) con el listener HTTPS del dominio agregado aparte, cert Let's Encrypt
**prod**, login OTP + allowlist (SDD 14) y asistente AI vía OpenRouter (modelo free). Imagen
construida con Kaniko (SDD 15), migraciones automáticas (SDD 16).
