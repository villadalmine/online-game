# TLS público con cert-manager + Gateway API (cruzdelsur.cybercirujas.club)

El dominio se sirve por **Gateway API** (Cilium). El TLS termina en el **Gateway compartido**
`cluster-gateway` (ns `gateway`), no en el chart del juego. Por eso el cert vive acá y no en
`deploy/helm/`.

**Estado del cluster (verificado):** cert-manager v1.20.1 con `enableGatewayAPI: true` ✅;
Gateway `cluster-gateway` con listener `:80` (`from: All`) ✅; **no hay** ClusterIssuer ACME ❌
(solo CA interna, que no sirve para un dominio público).

## Dónde va el dominio

En el chart: **`gateway.host`**.

```sh
helm upgrade --install online-game deploy/helm \
  --set gateway.enabled=true \
  --set gateway.host=cruzdelsur.cybercirujas.club \
  --set gateway.name=cluster-gateway \
  --set gateway.namespace=gateway
```

## Pasos para el cert (cert-manager lo pide solo)

1. **Crear el ClusterIssuer de Let's Encrypt** (editá el email). Empezá por staging:
   ```sh
   kubectl apply -f deploy/gateway-tls/clusterissuer-letsencrypt.yaml
   kubectl get clusterissuer letsencrypt-staging letsencrypt-prod   # READY=True
   ```

2. **Agregar el listener HTTPS + la annotation al Gateway** (aditivo, no afecta otros tenants):
   ```sh
   kubectl annotate gateway cluster-gateway -n gateway \
     cert-manager.io/cluster-issuer=letsencrypt-prod --overwrite
   kubectl patch gateway cluster-gateway -n gateway --type=json -p '[
     {"op":"add","path":"/spec/listeners/-","value":{
       "name":"cruzdelsur-https","hostname":"cruzdelsur.cybercirujas.club",
       "port":443,"protocol":"HTTPS",
       "allowedRoutes":{"namespaces":{"from":"All"}},
       "tls":{"mode":"Terminate","certificateRefs":[
         {"group":"","kind":"Secret","name":"cruzdelsur-tls","namespace":"gateway"}]}}}]'
   ```
   (Ver `gateway-https-listener.yaml` para la variante `kubectl edit`.) El **gateway shim** de
   cert-manager ve la annotation + el listener y **crea el Certificate solo**, llenando el
   Secret `cruzdelsur-tls`.

3. **Verificar la emisión**:
   ```sh
   kubectl get certificate -n gateway
   kubectl describe certificate cruzdelsur-tls -n gateway   # Events: Issued
   kubectl get order,challenge -n gateway                   # mientras resuelve
   ```
   Probá staging primero (`cert-manager.io/cluster-issuer=letsencrypt-staging`); cuando emita,
   cambiá la annotation a `letsencrypt-prod` y borrá el secret para forzar reemisión:
   `kubectl delete secret cruzdelsur-tls -n gateway`.

4. **Listo**: `https://cruzdelsur.cybercirujas.club` → la app (el HTTPRoute del chart liga por
   hostname al nuevo listener). Para forzar HTTP→HTTPS, agregá un HTTPRoute de redirect en el
   listener `:80` (opcional).

## Requisito de red (HTTP-01)

`cruzdelsur.cybercirujas.club` resuelve a `81.207.69.100` (pública). Para HTTP-01, ese **`:80`
debe llegar al Gateway** (`192.168.178.200`) desde internet (port-forward/NAT). El challenge es
`http://cruzdelsur.cybercirujas.club/.well-known/acme-challenge/...`.

### Si no podés exponer el :80 → DNS-01
Cambiá el `solvers:` del ClusterIssuer por un `dns01` con tu proveedor de DNS de
`cybercirujas.club` (ej. Cloudflare con un Secret de API token). DNS-01 **no necesita
reachability entrante** — solo credenciales del DNS. El resto (listener + secret + shim) es igual.
