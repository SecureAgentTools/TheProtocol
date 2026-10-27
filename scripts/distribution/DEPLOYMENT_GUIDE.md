# Self-Hosted Docker Registry — Deployment Guide

Serves TheProtocol distribution images at `images.theprotocol.cloud`.
Runs alongside the main stack on the Hetzner production server.

## Prerequisites

- A server (<your-host-ip>) with nginx already running
- Docker + Docker Compose installed
- certbot installed (`apt install certbot python3-certbot-nginx`)

## Setup Steps

### 1. DNS Record

Add an A record for the image registry subdomain:

```
images.theprotocol.cloud  →  <your-host-ip>
```

Wait for propagation (check with `dig images.theprotocol.cloud`).

### 2. TLS Certificate

```bash
certbot certonly --nginx -d images.theprotocol.cloud
```

### 3. Install Nginx Config

```bash
cp nginx-images.conf /etc/nginx/sites-available/images.theprotocol.cloud
ln -sf /etc/nginx/sites-available/images.theprotocol.cloud /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

### 4. Initialize Auth

```bash
cd /opt/theprotocol/stack/Agentvault2_dev/scripts/distribution
./registry-auth-manager.sh init
```

Save the printed admin credentials securely. This is the push account.

### 5. Start the Registry

```bash
docker compose -f docker-compose.image-registry.yml up -d
```

Verify health:

```bash
curl -s https://images.theprotocol.cloud/v2/ | head
# Should return 401 (auth required) — this confirms the registry is running
```

### 6. Login and Push Images

```bash
# Login with the admin credentials from step 4
docker login images.theprotocol.cloud -u theprotocol-admin -p <password>

# Build and push distribution images
./build.sh --push
```

## Operator Management

### Add an operator

```bash
./registry-auth-manager.sh add <operator-id> [password]
# If password omitted, a random one is generated
```

### Remove an operator

```bash
./registry-auth-manager.sh remove <operator-id>
docker restart theprotocol_image_registry
```

### List operators

```bash
./registry-auth-manager.sh list
```

## Operator Pull Instructions

Operators receive their credentials and run:

```bash
docker login images.theprotocol.cloud -u <operator-id> -p <password>
docker compose -f docker-compose.operator.yml --env-file .env.operator up -d
```

## Maintenance

### View logs

```bash
docker logs theprotocol_image_registry --tail 50
```

### Restart

```bash
docker restart theprotocol_image_registry
```

### Storage

Registry data is stored in the `theprotocol_image_registry_data` Docker volume.
To check disk usage:

```bash
docker system df -v | grep image_registry
```
