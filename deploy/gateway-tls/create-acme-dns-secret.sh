#!/usr/bin/env bash
# Crea (idempotente) el secret `acme-dns-account` que usan los ClusterIssuer de Let's Encrypt
# (DNS-01 vía acme-dns). El Helm chart NO lo crea a propósito: un secret con credenciales no va
# al repo en claro. Este es el "dueño" reproducible del secret.
#
# Uso:
#   1) Registrá una cuenta acme-dns (si no tenés):
#        curl -s -X POST https://auth.acme-dns.io/register
#   2) En Namecheap (a mano, sin API), CNAME estático por hostname:
#        _acme-challenge.<host>   CNAME   <subdomain>.auth.acme-dns.io.
#   3) cp acme-dns-account.example.json acme-dns-account.json   # (gitignored) y completá creds
#   4) ./create-acme-dns-secret.sh
#
# Idempotente: re-correrlo actualiza el secret sin romper. Usa server-side apply para NO dejar
# la annotation last-applied-configuration (que duplicaría la credencial en el objeto).
set -euo pipefail

NS="${NS:-cert-manager}"
DIR="$(cd "$(dirname "$0")" && pwd)"
CRED="${1:-$DIR/acme-dns-account.json}"

if [ ! -f "$CRED" ]; then
  echo "ERROR: falta '$CRED'."
  echo "       cp '$DIR/acme-dns-account.example.json' '$CRED' y completá las credenciales reales."
  exit 1
fi

kubectl create secret generic acme-dns-account \
  --namespace "$NS" \
  --from-file=credentials.json="$CRED" \
  --dry-run=client -o yaml \
  | kubectl apply --server-side --field-manager=acme-dns-bootstrap -f -

echo "OK: secret 'acme-dns-account' en ns '$NS' (key credentials.json)."
