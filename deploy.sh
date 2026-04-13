#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════
# deploy.sh — SurplusAI Marketplace Deployment Script
# AEGIS-AI / ZHURONG SL
# ══════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="surplusai"
DOMAIN="${DOMAIN:-surplusai.aegis-ai.es}"
ENV_FILE="${SCRIPT_DIR}/.env.prod"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1" >&2; }
info()  { echo -e "${BLUE}[i]${NC} $1"; }

usage() {
    cat <<EOF
Uso: ./deploy.sh <target> [opciones]

Targets:
  local       Deploy local con Docker Compose (testing)
  vps         Deploy en VPS (Hetzner/DigitalOcean) vía SSH
  railway     Deploy en Railway
  flyio       Deploy en Fly.io

Opciones:
  --env FILE       Archivo .env personalizado (default: .env.prod)
  --domain DOMAIN  Dominio (default: surplusai.aegis-ai.es)
  --ssh USER@HOST  Conexión SSH para VPS
  --skip-ssl       No configurar SSL (VPS)
  --dry-run        Mostrar comandos sin ejecutar

Ejemplos:
  ./deploy.sh local
  ./deploy.sh vps --ssh root@168.119.x.x --domain surplusai.aegis-ai.es
  ./deploy.sh railway
  ./deploy.sh flyio
EOF
    exit 0
}

# ── Parse arguments ──────────────────────────────────────────────
TARGET=""
SSH_HOST=""
SKIP_SSL=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        local|vps|railway|flyio) TARGET="$1" ;;
        --env)      ENV_FILE="$2"; shift ;;
        --domain)   DOMAIN="$2"; shift ;;
        --ssh)      SSH_HOST="$2"; shift ;;
        --skip-ssl) SKIP_SSL=true ;;
        --dry-run)  DRY_RUN=true ;;
        -h|--help)  usage ;;
        *) err "Opción desconocida: $1"; usage ;;
    esac
    shift
done

[[ -z "$TARGET" ]] && { err "Target requerido"; usage; }

run_cmd() {
    if $DRY_RUN; then
        echo "  [dry-run] $*"
    else
        "$@"
    fi
}

# ── Generate .env.prod if missing ────────────────────────────────
generate_env() {
    if [[ -f "$ENV_FILE" ]]; then
        info "Usando env existente: $ENV_FILE"
        return
    fi

    warn "Generando $ENV_FILE — EDITA las credenciales antes de deploy real"
    cat > "$ENV_FILE" <<'ENVEOF'
# SurplusAI Production Environment
# ⚠️ CAMBIA ESTOS VALORES ANTES DE DEPLOY

# Database
DB_USER=surplusai
DB_PASSWORD=CAMBIAR_password_seguro_2026
DB_NAME=surplusai_prod

# Redis
REDIS_PASSWORD=CAMBIAR_redis_password_2026

# JWT / Security
SECRET_KEY=CAMBIAR_jwt_secret_key_muy_largo_2026
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Email (Gmail App Password)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=vitin.ceo@gmail.com
SMTP_PASSWORD=CAMBIAR_app_password
SMTP_FROM_EMAIL=vitin.ceo@gmail.com

# Notifications
NOTIFICATIONS_ENABLED=true
TELEGRAM_BOT_TOKEN=CAMBIAR_token
TELEGRAM_CHAT_ID=CAMBIAR_chat_id

# App config
WORKERS=4
LOG_LEVEL=info
ENVEOF
    log "Archivo $ENV_FILE generado — edítalo con credenciales reales"
}

# ── Pre-flight checks ────────────────────────────────────────────
preflight() {
    info "Verificaciones previas para target: $TARGET"

    # Check required files
    local required_files=(
        "$SCRIPT_DIR/Dockerfile.prod"
        "$SCRIPT_DIR/docker-compose.prod.yml"
        "$SCRIPT_DIR/backend/requirements.txt"
        "$SCRIPT_DIR/backend/main.py"
    )

    for f in "${required_files[@]}"; do
        if [[ ! -f "$f" ]]; then
            err "Archivo requerido no encontrado: $f"
            exit 1
        fi
    done
    log "Archivos del proyecto verificados"

    # Check tools per target
    case $TARGET in
        local|vps) command -v docker >/dev/null || { err "Docker no instalado"; exit 1; } ;;
        railway)   command -v railway >/dev/null || { err "Railway CLI no instalada: npm i -g @railway/cli"; exit 1; } ;;
        flyio)     command -v fly >/dev/null || { err "Fly CLI no instalada: brew install flyctl"; exit 1; } ;;
    esac
    log "Herramientas CLI verificadas"
}

# ══════════════════════════════════════════════════════════════════
# DEPLOY: Local (Docker Compose)
# ══════════════════════════════════════════════════════════════════
deploy_local() {
    info "Deploy local con Docker Compose..."
    generate_env

    cd "$SCRIPT_DIR"

    # Build
    log "Construyendo imagen Docker..."
    run_cmd docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE" build

    # Start services
    log "Iniciando servicios..."
    run_cmd docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE" up -d

    # Wait for health
    info "Esperando a que los servicios estén healthy..."
    local max_wait=60
    local waited=0
    while [[ $waited -lt $max_wait ]]; do
        if docker compose -f docker-compose.prod.yml ps | grep -q "healthy"; then
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done

    # Check status
    echo ""
    run_cmd docker compose -f docker-compose.prod.yml ps
    echo ""
    log "Deploy local completo"
    info "API: http://localhost:8000"
    info "Docs: http://localhost:8000/docs"
    info "Health: http://localhost:8000/health"
}

# ══════════════════════════════════════════════════════════════════
# DEPLOY: VPS (SSH + Docker Compose + Let's Encrypt)
# ══════════════════════════════════════════════════════════════════
deploy_vps() {
    [[ -z "$SSH_HOST" ]] && { err "Requiere --ssh USER@HOST"; exit 1; }

    info "Deploy en VPS: $SSH_HOST"
    generate_env

    local REMOTE_DIR="/opt/$PROJECT_NAME"

    # Step 1: Setup server
    log "Preparando servidor..."
    run_cmd ssh "$SSH_HOST" bash <<SETUP
set -euo pipefail
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-plugin curl certbot > /dev/null 2>&1
systemctl enable --now docker
mkdir -p $REMOTE_DIR/deploy/ssl
echo "Servidor preparado"
SETUP

    # Step 2: Copy files
    log "Copiando archivos al servidor..."
    run_cmd rsync -avz --progress \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude '.git' \
        --exclude 'node_modules' \
        --exclude '*.db' \
        --exclude '.env' \
        "$SCRIPT_DIR/" "$SSH_HOST:$REMOTE_DIR/"

    # Copy env file
    run_cmd scp "$ENV_FILE" "$SSH_HOST:$REMOTE_DIR/.env"

    # Step 3: SSL with Let's Encrypt
    if ! $SKIP_SSL; then
        log "Configurando SSL con Let's Encrypt..."
        run_cmd ssh "$SSH_HOST" bash <<SSL
set -euo pipefail
certbot certonly --standalone -d $DOMAIN --non-interactive --agree-tos -m vitin.ceo@gmail.com || true
if [[ -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem ]]; then
    cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem $REMOTE_DIR/deploy/ssl/cert.pem
    cp /etc/letsencrypt/live/$DOMAIN/privkey.pem $REMOTE_DIR/deploy/ssl/key.pem
    echo "SSL configurado para $DOMAIN"
else
    echo "SSL no disponible, generando certificado self-signed..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout $REMOTE_DIR/deploy/ssl/key.pem \
        -out $REMOTE_DIR/deploy/ssl/cert.pem \
        -subj "/C=ES/ST=Madrid/L=Madrid/O=ZHURONG SL/CN=$DOMAIN"
fi
SSL
    fi

    # Step 4: Build and start
    log "Construyendo y arrancando servicios..."
    run_cmd ssh "$SSH_HOST" bash <<DEPLOY
set -euo pipefail
cd $REMOTE_DIR
docker compose -f docker-compose.prod.yml --env-file .env build
docker compose -f docker-compose.prod.yml --env-file .env up -d
echo "Servicios arrancados"
docker compose -f docker-compose.prod.yml ps
DEPLOY

    # Step 5: Setup auto-renewal cron
    if ! $SKIP_SSL; then
        run_cmd ssh "$SSH_HOST" bash <<CRON
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet --post-hook 'cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem $REMOTE_DIR/deploy/ssl/cert.pem && cp /etc/letsencrypt/live/$DOMAIN/privkey.pem $REMOTE_DIR/deploy/ssl/key.pem && docker restart aegis-food-nginx-prod'") | crontab - 2>/dev/null || true
CRON
    fi

    echo ""
    log "Deploy VPS completo"
    info "URL: https://$DOMAIN"
    info "API Docs: https://$DOMAIN/docs"
    info "SSH: ssh $SSH_HOST"
}

# ══════════════════════════════════════════════════════════════════
# DEPLOY: Railway
# ══════════════════════════════════════════════════════════════════
deploy_railway() {
    info "Deploy en Railway..."
    cd "$SCRIPT_DIR"

    # Check login
    railway whoami 2>/dev/null || { err "Ejecuta: railway login"; exit 1; }

    # Init project if needed
    if [[ ! -f ".railway/config.json" ]]; then
        warn "Inicializando proyecto Railway..."
        run_cmd railway init
    fi

    # Set environment variables from .env.prod
    if [[ -f "$ENV_FILE" ]]; then
        log "Configurando variables de entorno..."
        while IFS='=' read -r key value; do
            [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
            key=$(echo "$key" | xargs)
            value=$(echo "$value" | xargs)
            [[ -z "$value" || "$value" == "CAMBIAR"* ]] && { warn "Salta $key (no configurado)"; continue; }
            run_cmd railway variables set "$key=$value" 2>/dev/null || true
        done < "$ENV_FILE"
    fi

    # Deploy
    log "Desplegando..."
    run_cmd railway up --detach

    echo ""
    log "Deploy Railway completo"
    info "Dashboard: railway open"
    info "Logs: railway logs"
}

# ══════════════════════════════════════════════════════════════════
# DEPLOY: Fly.io
# ══════════════════════════════════════════════════════════════════
deploy_flyio() {
    info "Deploy en Fly.io..."
    cd "$SCRIPT_DIR"

    # Check login
    fly auth whoami 2>/dev/null || { err "Ejecuta: fly auth login"; exit 1; }

    # Launch if first time
    if ! fly status 2>/dev/null; then
        warn "Primera vez — lanzando app..."
        run_cmd fly launch --name "$PROJECT_NAME" \
            --region mad \
            --no-deploy \
            --dockerfile Dockerfile.prod
    fi

    # Set secrets from .env.prod
    if [[ -f "$ENV_FILE" ]]; then
        log "Configurando secrets..."
        local secrets_args=()
        while IFS='=' read -r key value; do
            [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
            key=$(echo "$key" | xargs)
            value=$(echo "$value" | xargs)
            [[ -z "$value" || "$value" == "CAMBIAR"* ]] && continue
            secrets_args+=("$key=$value")
        done < "$ENV_FILE"
        if [[ ${#secrets_args[@]} -gt 0 ]]; then
            run_cmd fly secrets set "${secrets_args[@]}"
        fi
    fi

    # Create Postgres if needed
    if ! fly postgres list 2>/dev/null | grep -q "$PROJECT_NAME-db"; then
        warn "Creando base de datos Postgres..."
        run_cmd fly postgres create --name "$PROJECT_NAME-db" --region mad --vm-size shared-cpu-1x --initial-cluster-size 1 --volume-size 1
        run_cmd fly postgres attach "$PROJECT_NAME-db"
    fi

    # Deploy
    log "Desplegando..."
    run_cmd fly deploy --dockerfile Dockerfile.prod --region mad

    echo ""
    log "Deploy Fly.io completo"
    info "URL: https://$PROJECT_NAME.fly.dev"
    info "Logs: fly logs"
    info "Status: fly status"
}

# ══════════════════════════════════════════════════════════════════
# Post-deploy health check
# ══════════════════════════════════════════════════════════════════
post_deploy_check() {
    local url=""
    case $TARGET in
        local)   url="http://localhost:8000/health" ;;
        vps)     url="https://$DOMAIN/health" ;;
        railway) url=$(railway domain 2>/dev/null || echo "") ;;
        flyio)   url="https://$PROJECT_NAME.fly.dev/health" ;;
    esac

    if [[ -n "$url" ]]; then
        info "Verificando health check: $url"
        sleep 3
        if curl -sf --max-time 10 "$url" >/dev/null 2>&1; then
            log "Health check OK"
        else
            warn "Health check no responde aún — puede necesitar más tiempo"
        fi
    fi
}

# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  SurplusAI Deploy — AEGIS-AI / ZHURONG SL"
echo "  Target: $TARGET | Domain: $DOMAIN"
echo "═══════════════════════════════════════════════════════"
echo ""

preflight

case $TARGET in
    local)   deploy_local ;;
    vps)     deploy_vps ;;
    railway) deploy_railway ;;
    flyio)   deploy_flyio ;;
esac

post_deploy_check

echo ""
log "Deploy completado exitosamente"
echo ""
