# TLS público con cert-manager + Gateway API

El dominio se sirve por **Gateway API** (Cilium). El TLS termina en el **Gateway compartido**
(no en el chart del juego), así que el cert vive acá y no en `deploy/helm/`.

> Requiere cert-manager con `enableGatewayAPI: true` (el "gateway shim") en el cluster.

## Dónde va el dominio

En el chart: **`gateway.host`**.

```sh
helm upgrade --install online-game deploy/helm \
  --set gateway.enabled=true \
  --set gateway.host=<DOMINIO> \
  --set gateway.name=<GATEWAY> \
  --set gateway.namespace=<GATEWAY_NS>
```

## Pasos para el cert (cert-manager lo pide solo)

1. **ClusterIssuer de Let's Encrypt** (editá email + solver). Empezá por staging:
   ```sh
   kubectl apply -f deploy/gateway-tls/clusterissuer-letsencrypt.yaml
   kubectl get clusterissuer letsencrypt-staging letsencrypt-prod   # READY=True
   ```

2. **Listener HTTPS + annotation en el Gateway** (aditivo; ver `gateway-https-listener.yaml`):
   ```sh
   kubectl annotate gateway <GATEWAY> -n <GATEWAY_NS> \
     cert-manager.io/cluster-issuer=letsencrypt-prod --overwrite
   # + agregar el listener HTTPS con hostname=<DOMINIO> y certificateRefs name=app-tls
   ```
   El shim ve la annotation + el listener y **crea el Certificate solo**, llenando `app-tls`.

3. **Verificar**:
   ```sh
   kubectl get certificate -n <GATEWAY_NS>
   kubectl describe certificate app-tls -n <GATEWAY_NS>   # Events: Issued
   kubectl get order,challenge -n <GATEWAY_NS>            # mientras resuelve
   ```
   Probá staging; cuando emita, cambiá la annotation a `letsencrypt-prod` y borrá el secret para
   forzar reemisión: `kubectl delete secret app-tls -n <GATEWAY_NS>`.

4. **Listo**: `https://<DOMINIO>` → la app (el HTTPRoute del chart liga por hostname al listener).

## Validación del challenge: DNS-01 vs HTTP-01

- **DNS-01** (recomendado detrás de NAT / si solo tenés el `:443` expuesto): no necesita tráfico
  HTTP entrante. Con proveedor que tenga solver nativo (cloudflare/route53/etc.) usás un token.
  Con un proveedor SIN solver nativo (registradores con API limitada/no apta), usá **acme-dns**:
  corrés un acme-dns, delegás `_acme-challenge.<dominio>` con un CNAME estático y cert-manager
  escribe los TXT ahí (solver built-in). Es el ejemplo por defecto del ClusterIssuer.
- **HTTP-01**: necesita el `:80` alcanzable desde internet llegando al Gateway. Si ese es tu caso,
  cambiá el `solvers:` por `http01.gatewayHTTPRoute` apuntando al Gateway.

## Frente TCP / SNI passthrough (si hay un proxy delante)

Si un proxy L4 (haproxy/nginx stream) recibe el `:443` y enruta por SNI en **modo TCP
passthrough**, su backend debe apuntar a la **VIP del Service LoadBalancer del Gateway**
(`kubectl get svc -n <GATEWAY_NS>` → la external IP), **no** a un nodo/controlplane: ahí termina
el TLS con el cert de Let's Encrypt. No termines TLS en el proxy (dejá pasar el ClientHello).
