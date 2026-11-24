#!/usr/bin/env bash
# Deploy or update the whole stack, in dependency order. Run on the server:
#   ./k8s/deploy.sh                 # deploy :latest
#   ./k8s/deploy.sh <commit-sha>    # deploy / roll back to a specific CI build
set -euo pipefail

cd "$(dirname "$0")"
TAG="${1:-latest}"
NS=chat

if [[ ! -f 01-secret.yaml ]]; then
  echo "k8s/01-secret.yaml is missing. Create it first:" >&2
  echo "  cp k8s/01-secret.example.yaml k8s/01-secret.yaml && nano k8s/01-secret.yaml" >&2
  exit 1
fi
if grep -q "change_this\|generate_a_random" 01-secret.yaml; then
  echo "k8s/01-secret.yaml still contains placeholder values. Edit it first." >&2
  exit 1
fi

echo "==> Namespace and secrets"
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-secret.yaml

echo "==> PostgreSQL, Redis, RabbitMQ"
kubectl apply -f 10-postgres.yaml -f 11-redis.yaml -f 12-rabbitmq.yaml
kubectl rollout status statefulset/postgres -n "$NS" --timeout=300s
kubectl rollout status statefulset/redis    -n "$NS" --timeout=300s
kubectl rollout status statefulset/rabbitmq -n "$NS" --timeout=300s

echo "==> Database migration (image tag: $TAG)"
kubectl delete job migrate -n "$NS" --ignore-not-found
sed "s|pinsara23/distributed-chat:latest|pinsara23/distributed-chat:$TAG|" 20-migrate-job.yaml | kubectl apply -f -
if ! kubectl wait --for=condition=complete job/migrate -n "$NS" --timeout=300s; then
  echo "Migration failed; chat servers were NOT updated. Logs:" >&2
  kubectl logs job/migrate -n "$NS" --all-containers >&2 || true
  exit 1
fi

echo "==> Chat servers"
kubectl apply -f 30-chat.yaml
kubectl set image deployment/chat chat="pinsara23/distributed-chat:$TAG" -n "$NS"
# Pull :latest again even when the manifest did not change.
[[ "$TAG" == "latest" ]] && kubectl rollout restart deployment/chat -n "$NS"
kubectl rollout status deployment/chat -n "$NS" --timeout=300s

echo "==> Web UI, ingress, backups"
kubectl apply -f 40-web.yaml -f 50-ingress.yaml -f 60-backup-cronjob.yaml
kubectl rollout restart deployment/web -n "$NS"
kubectl rollout status deployment/web -n "$NS" --timeout=180s

echo
kubectl get pods -n "$NS" -o wide
echo
echo "Done. Open http://<server-ip>/ (HTTPS needed for encryption, see k8s/README.md)."
