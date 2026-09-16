# Reverse proxy (homelab)

RMT-Debrid is a headless web UI — put it behind Caddy/Traefik/NGINX with TLS and
optional forward-auth (Authelia/Authentik). No Docker required.

## Basics

- Upstream: `http://127.0.0.1:8000` (or `--host/--port` values). Proxy `/api` and
  `/ws` (WebSocket) to the same upstream; everything else is the static UI.
- Health: `GET /api/health` (liveness), `GET /api/ready` (readiness, checks DB +
  download-folder writability), `GET /metrics` (Prometheus, unauthenticated counters only).
- Sessions are persistent cookies (`rmt_session`, 30d, `sessions.json`). Extra
  service tokens via `RMT_API_TOKENS=tok1,tok2` using the `X-API-Key` header.

## Caddy

```caddy
rmt.example.lan {
    reverse_proxy 127.0.0.1:8000
}
```

## NGINX

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Traefik

```yaml
services:
  rmt:
    loadBalancer:
      servers:
        - url: http://host.docker.internal:8000
```

## Forward-auth note

If you use Authelia/Authentik in front, you can leave `APP_PASSWORD` empty and
rely on the proxy, or keep both layers. API clients should send `X-API-Key`
matching `API_KEY` or one of `RMT_API_TOKENS`.
