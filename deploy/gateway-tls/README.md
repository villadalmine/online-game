# TLS público para cruzdelsur.cybercirujas.club (Let's Encrypt + Gateway API)

El dominio se sirve por **Gateway API (Cilium)**; el TLS termina en el **Gateway**. El cert lo emite
**cert-manager** con **Let's Encrypt** vía **DNS-01 / acme-dns.io** (no necesita exponer el `:80`).

## Qué crea el Helm chart vs. qué es prerequisito

El chart (`deploy/helm`, con `values-cruzdelsur.example.yaml`) **crea y ownea**:
- los `ClusterIssuer` `letsencrypt-staging` / `letsencrypt-prod` (`letsencrypt.enabled=true`)
- el `Gateway` propio + listener HTTPS (`gateway.create=true`, `lbip`)
- el `Certificate` (`gateway.tls.enabled=true`)
- el `HTTPRoute` (`gateway.enabled=true`)

**Lo único que el chart NO crea** (a propósito — un secret no va al repo en claro):
- el **secret `acme-dns-account`** en el ns `cert-manager` con las credenciales de tu cuenta acme-dns.

Ese secret es el prerequisito reproducible de este directorio.

## Crear el secret acme-dns (una sola vez, reproducible)

```sh
# 1) Registrar cuenta acme-dns (si no tenés):
curl -s -X POST https://auth.acme-dns.io/register
#    -> guardá username/password/fulldomain/subdomain

# 2) CNAME estático en Namecheap (a mano, sin API), por hostname:
#    _acme-challenge.cruzdelsur   CNAME   <subdomain>.auth.acme-dns.io.
#    (¡el guion bajo "_" adelante es OBLIGATORIO!)

# 3) Completar credenciales y crear el secret:
cp acme-dns-account.example.json acme-dns-account.json    # gitignored
$EDITOR acme-dns-account.json
./create-acme-dns-secret.sh
```

`create-acme-dns-secret.sh` es **idempotente** (server-side apply, sin annotation que filtre la
credencial). Verificá la delegación DNS antes de emitir:

```sh
dig _acme-challenge.<HOSTNAME> CNAME +short
# debe devolver: <subdomain>.auth.acme-dns.io.
```

## Desplegar

```sh
helm upgrade --install galaxy ../helm -n online-game --create-namespace \
  -f ../helm/values-cruzdelsur.example.yaml
```

Podés arrancar con `gateway.tls.issuer: letsencrypt-staging`; cuando emita verde, pasá a
`letsencrypt-prod` (`helm upgrade` + `kubectl delete secret cruzdelsur-tls -n gateway` para forzar la
reemisión).

## HAProxy (SNI passthrough en la Mac mini)

El router manda el `:443` a HAProxy, que enruta por SNI y reenvía el TCP crudo al Gateway (el TLS
termina en el Gateway, no en HAProxy). El backend apunta a la **VIP del LoadBalancer del Gateway**
(`kubectl get svc -n gateway` → la external IP):

```haproxy
backend app_backend
    mode tcp
    server app_server1 <IP-DEL-GATEWAY>:443 check maxconn 5
    timeout queue 5s
```

> Camino vigente: `gateway.create=false` + `gateway.name=cluster-gateway` (se reusa el Gateway
> compartido). La IP del backend es la VIP del `cluster-gateway`, y el **listener HTTPS** del
> hostname hay que agregarlo aparte (Helm no edita un Gateway ajeno) — ver
> `gateway-https-listener.yaml`. La variante de Gateway dedicado quedó descartada.

## Archivos

- `acme-dns-account.example.json` — plantilla de credenciales (placeholders, **se versiona**).
- `create-acme-dns-secret.sh` — crea el secret desde `acme-dns-account.json` (gitignored).
- `clusterissuer-letsencrypt.yaml` / `gateway-https-listener.yaml` — **referencia/legacy** (variante
  HTTP-01 + patch al cluster-gateway). El camino vigente es el del chart (arriba).
