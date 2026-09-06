# Reverse proxy local: exemple minimal (Nginx)

Objectif: exposer localement l'API sur 127.0.0.1 et laisser un reverse proxy (Nginx) en frontal, sans élargir la surface réseau.

- API Uvicorn bindée sur 127.0.0.1:8000
- Nginx écoute sur 127.0.0.1:8080
- Autorisation `/metrics` via allow-list + option XFF désactivée par défaut (METRICS_TRUST_XFF=0)

Bloc Nginx (extrait):

```nginx
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Request-ID $request_id;
        proxy_pass http://127.0.0.1:8000;
    }

    # Optionnel: permettre X-Forwarded-For si vous activez METRICS_TRUST_XFF=1 côté app
    # proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Notes:

- Par défaut, l'app ne fait pas confiance à X-Forwarded-For. Activez `METRICS_TRUST_XFF=1` uniquement si vous contrôlez le proxy et les headers.
- Conservez `METRICS_ALLOWED_HOSTS` restreint (ex: `127.0.0.1`) pour un usage mono-PC.
- Sur Windows, vous pouvez utiliser `nginx-windows` pour des tests locaux, mais ce n'est pas requis pour une utilisation personnelle simple.
