# Deploying on Kubernetes (k3s, single Ubuntu server)

```
browser ──► Traefik ingress :80/:443 ──► web (nginx: UI + /backend/ proxy)
                                            │
                                            ▼
                                  chat Service :8000 ──► chat pods ×3
                                                           │  │  │
                               postgres-0 ◄────────────────┘  │  └──► rabbitmq-0
                                                    redis-0 ◄─┘
```

| File | What it runs | Compose equivalent |
|---|---|---|
| `00-namespace.yaml` | namespace `chat` | — |
| `01-secret.example.yaml` | passwords, JWT key (copy to `01-secret.yaml`) | `.env` |
| `10-postgres.yaml` | PostgreSQL 15 + 5 Gi volume | `postgres` |
| `11-redis.yaml` | Redis 7 + 1 Gi volume | `redis` |
| `12-rabbitmq.yaml` | RabbitMQ 3 + 2 Gi volume | `rabbitmq` |
| `20-migrate-job.yaml` | `alembic upgrade head`, once per deploy | `migrate` |
| `30-chat.yaml` | 3 chat replicas, `SERVER_ID` = pod name | `chat_server_1..3` |
| `40-web.yaml` | nginx with the built UI, proxies `/backend/<port>/…` to the chat pods | `frontend-ts/serve.py` + `nginx` |
| `50-ingress.yaml` | Traefik ingress (public entry point) | `nginx` port 80 |
| `60-backup-cronjob.yaml` | daily `pg_dump` to `/srv/chat-backups` | `postgres_backup` |
| `deploy.sh` | applies everything in order | `docker compose up -d` |

Expected memory use: about 2 GB in total, including k3s itself.

Images come from Docker Hub, built by `.github/workflows/build.yml` on every
push to `new-version`:
`pinsara23/distributed-chat` (backend) and `pinsara23/distributed-chat-web` (UI).
**Push once after adding these files**, so the web image exists, before the
first deploy.

---

## 1. One-time server setup (Ubuntu)

```bash
# Keep running with the lid closed
sudo sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=ignore/; s/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind

# Updates + git
sudo apt update && sudo apt upgrade -y && sudo apt install -y git curl

# k3s (Kubernetes + Traefik ingress + local-path storage)
curl -sfL https://get.k3s.io | sh -

# Use kubectl without sudo
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$USER": ~/.kube/config
echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc && source ~/.bashrc

kubectl get nodes          # STATUS should be Ready
```

Give the server a fixed IP (DHCP reservation in the router is easiest).

## 2. Get the code and create the secret

```bash
git clone -b new-version https://github.com/<your-user>/<your-repo>.git chat
cd chat

cp k8s/01-secret.example.yaml k8s/01-secret.yaml
python3 -c "import secrets; print(secrets.token_hex(24))"   # -> POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_hex(24))"   # -> RABBITMQ_PASSWORD
python3 -c "import secrets; print(secrets.token_hex(32))"   # -> JWT_SECRET_KEY
nano k8s/01-secret.yaml
```

Use letters and digits only for the passwords (they go into connection URLs).
`01-secret.yaml` is git-ignored, so keep a copy somewhere safe.

## 3. Deploy

```bash
chmod +x k8s/deploy.sh
./k8s/deploy.sh
```

The first run takes a few minutes while the images are pulled. Then open
`http://<server-ip>/`. The page loads, but **login and encryption need HTTPS**
(step 4).

## 4. HTTPS (required for the browser's end-to-end encryption)

Web Crypto (X25519) only works on `https://` or `localhost`. Pick one:

### A) Tailscale (easiest; valid certificate, no router changes)
Works from any device signed in to your Tailscale account, at home or away.
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg http://localhost:80
tailscale serve status        # shows https://<server-name>.<tailnet>.ts.net
```
(Enable "HTTPS Certificates" and MagicDNS in the Tailscale admin console if
asked.) To make it public on the internet as well, use `tailscale funnel`
instead of `serve`.

### B) mkcert (home network only, self-made certificate authority)
```bash
sudo apt install -y mkcert libnss3-tools
mkcert -install
mkcert <server-ip> chat.local          # creates <name>.pem and <name>-key.pem
kubectl create secret tls chat-tls -n chat --cert=<name>.pem --key=<name>-key.pem
```
Uncomment the `tls:` block in `50-ingress.yaml` and run
`kubectl apply -f k8s/50-ingress.yaml`. Every client device must trust the
mkcert root CA: copy `$(mkcert -CAROOT)/rootCA.pem` to it and install it as a
trusted root certificate.

## 5. Everyday operations

```bash
kubectl get pods -n chat                         # status
kubectl logs -n chat -l app=chat -f --prefix     # all chat server logs
kubectl logs -n chat job/migrate                 # migration output

# Update after a push (CI finished): pulls :latest, migrates, rolling restart
git pull && ./k8s/deploy.sh

# Deploy / roll back to a specific build (commit SHA from GitHub)
./k8s/deploy.sh <commit-sha>
kubectl rollout undo deployment/chat -n chat      # quick rollback, no migration

kubectl scale deployment/chat -n chat --replicas=5   # more chat servers

# RabbitMQ management UI at http://localhost:15672 on the machine running this
kubectl port-forward -n chat svc/rabbitmq 15672:15672

# psql
kubectl exec -it -n chat postgres-0 -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

# Backup now (files land in /srv/chat-backups)
kubectl create job -n chat --from=cronjob/postgres-backup backup-now-$(date +%s)
```

Fault-tolerance demo: `kubectl delete pod -n chat <chat-pod-name>` drops that
pod's WebSockets. Clients reconnect to another pod, and Kubernetes starts a
replacement automatically.

## Notes

- The UI's server picker (8001/8002/8003/8000) still works, but every choice
  goes through the same load-balanced `chat` Service. Kubernetes, not the
  browser, decides which pod handles the request.
- Data lives under `/var/lib/rancher/k3s/storage` on the server. Deleting the
  namespace (`kubectl delete ns chat`) **deletes the volumes too**.
- Remove everything: `kubectl delete ns chat`. Remove k3s:
  `/usr/local/bin/k3s-uninstall.sh`.
