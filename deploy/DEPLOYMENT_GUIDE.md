# AEGIS-FOOD Production Deployment Guide

Comprehensive guide for deploying the AEGIS-FOOD B2B Food Surplus Marketplace to production.

## Table of Contents

1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Docker Compose Deployment (VPS/Self-Hosted)](#docker-compose-deployment)
3. [Railway.app Deployment](#railwayapp-deployment)
4. [Fly.io Deployment](#flyio-deployment)
5. [SSL/TLS Certificate Setup](#ssltls-certificate-setup)
6. [Database Backup & Recovery](#database-backup--recovery)
7. [Monitoring & Logging](#monitoring--logging)
8. [Troubleshooting](#troubleshooting)
9. [Post-Deployment Steps](#post-deployment-steps)

---

## Pre-Deployment Checklist

Before deploying to any platform, ensure:

- [ ] All environment variables configured (see `.env.prod.example`)
- [ ] Database backup strategy in place
- [ ] SSL/TLS certificates obtained
- [ ] SMTP credentials verified
- [ ] Domain name configured with DNS records
- [ ] Firewall rules configured to allow 80/443 traffic
- [ ] Resource limits defined (CPU, memory, disk)
- [ ] Monitoring and alerting configured
- [ ] Backup and disaster recovery plan documented
- [ ] Load testing completed to verify capacity
- [ ] Security scan completed
- [ ] Database migration tested on staging

---

## Docker Compose Deployment (VPS/Self-Hosted)

### Prerequisites

- Linux server (Ubuntu 20.04 LTS or newer recommended)
- Docker 20.10+ and Docker Compose 2.0+
- At least 2GB RAM, 2 vCPU, 20GB disk
- Root or sudo access
- Domain name pointing to server IP

### Step 1: Server Setup

```bash
# Update system packages
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Create app user
sudo useradd -m -s /bin/bash aegis
sudo usermod -aG docker aegis

# Create application directory
sudo mkdir -p /opt/aegis-food
sudo chown aegis:aegis /opt/aegis-food
```

### Step 2: Clone Repository

```bash
sudo -u aegis git clone <your-repo-url> /opt/aegis-food
cd /opt/aegis-food
```

### Step 3: Configure Environment

```bash
# Copy environment template
cp deploy/.env.prod.example .env.prod

# Edit with your values
nano .env.prod

# Required values to set:
# - SECRET_KEY: Generate with: openssl rand -base64 32
# - DB_PASSWORD: Strong password for PostgreSQL
# - REDIS_PASSWORD: Strong password for Redis
# - SMTP_* variables for email
# - API_URL: Your domain URL
```

### Step 4: Setup SSL Certificates

```bash
# Create SSL directory
mkdir -p /opt/aegis-food/deploy/ssl

# Option A: Using Let's Encrypt (Recommended)
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot certonly --standalone -d aegis-food.com -d www.aegis-food.com
sudo cp /etc/letsencrypt/live/aegis-food.com/fullchain.pem /opt/aegis-food/deploy/ssl/cert.pem
sudo cp /etc/letsencrypt/live/aegis-food.com/privkey.pem /opt/aegis-food/deploy/ssl/key.pem
sudo chown aegis:aegis /opt/aegis-food/deploy/ssl/*
sudo chmod 600 /opt/aegis-food/deploy/ssl/*

# Option B: Using self-signed certificate (Testing only)
openssl req -x509 -newkey rsa:4096 -keyout deploy/ssl/key.pem -out deploy/ssl/cert.pem -days 365 -nodes
```

### Step 5: Start Services

```bash
# Create environment file with proper permissions
sudo -u aegis touch /opt/aegis-food/.env.prod.secure
sudo -u aegis chmod 600 /opt/aegis-food/.env.prod.secure

# Build images
sudo -u aegis docker-compose -f docker-compose.prod.yml build

# Start services
sudo -u aegis docker-compose -f docker-compose.prod.yml up -d

# Verify services are running
sudo -u aegis docker-compose -f docker-compose.prod.yml ps

# Check logs
sudo -u aegis docker-compose -f docker-compose.prod.yml logs -f backend
```

### Step 6: Verify Deployment

```bash
# Check health endpoint
curl https://aegis-food.com/health

# Access API documentation
# Visit https://aegis-food.com/docs in browser

# Check all containers
docker ps | grep aegis
```

### Step 7: Setup Auto-Renewal for SSL Certificates

```bash
# Create renewal script
cat > /opt/aegis-food/renew-cert.sh << 'EOF'
#!/bin/bash
certbot renew --quiet
cp /etc/letsencrypt/live/aegis-food.com/fullchain.pem /opt/aegis-food/deploy/ssl/cert.pem
cp /etc/letsencrypt/live/aegis-food.com/privkey.pem /opt/aegis-food/deploy/ssl/key.pem
cd /opt/aegis-food
docker-compose -f docker-compose.prod.yml restart nginx
EOF

chmod +x /opt/aegis-food/renew-cert.sh

# Add to crontab (runs daily)
crontab -e
# Add: 0 3 * * * /opt/aegis-food/renew-cert.sh
```

### Maintenance Commands

```bash
# View logs
docker-compose -f docker-compose.prod.yml logs -f backend
docker-compose -f docker-compose.prod.yml logs -f db

# Restart specific service
docker-compose -f docker-compose.prod.yml restart backend

# Backup database
docker-compose -f docker-compose.prod.yml exec db pg_dump -U postgres aegis_food_prod > backup.sql

# Restore database
docker-compose -f docker-compose.prod.yml exec -T db psql -U postgres aegis_food_prod < backup.sql

# Stop services
docker-compose -f docker-compose.prod.yml down

# Update application
git pull origin main
docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up -d
```

---

## Railway.app Deployment

### Prerequisites

- Railway account (https://railway.app)
- GitHub repository connected to Railway
- `railway` CLI installed locally

### Step 1: Install Railway CLI

```bash
npm install -g @railway/cli
railway login
```

### Step 2: Create Project

```bash
# Create new project
railway init

# Follow prompts to create project
```

### Step 3: Add PostgreSQL Plugin

```bash
# Add PostgreSQL database
railway add
# Select "PostgreSQL"
# Railway will create DATABASE_URL automatically
```

### Step 4: Add Redis Plugin

```bash
# Add Redis cache
railway add
# Select "Redis"
# Railway will create REDIS_URL automatically
```

### Step 5: Set Environment Secrets

```bash
# Set all required environment variables
railway secrets set SECRET_KEY=$(openssl rand -base64 32)
railway secrets set SMTP_SERVER=smtp.gmail.com
railway secrets set SMTP_PORT=587
railway secrets set SMTP_USERNAME=your-email@gmail.com
railway secrets set SMTP_PASSWORD=your-gmail-app-password
railway secrets set SMTP_FROM_EMAIL=noreply@aegis-food.com
railway secrets set NOTIFICATIONS_ENABLED=true
railway secrets set WORKERS=4
railway secrets set LOG_LEVEL=info

# Verify secrets are set
railway secrets
```

### Step 6: Configure Domain

```bash
# In Railway dashboard:
# 1. Go to Settings → Domains
# 2. Add your custom domain
# 3. Configure DNS records as instructed
```

### Step 7: Deploy

```bash
# Deploy using Git push
git push origin main

# Or manually trigger deploy
railway deploy

# View deployment logs
railway logs

# Monitor in real-time
railway status
```

### Railway Management Commands

```bash
# View current environment
railway env

# Scale up workers
railway variables set WORKERS=8

# View logs
railway logs --follow

# SSH into running container
railway shell

# List all apps
railway list

# Switch project
railway switch
```

---

## Fly.io Deployment

### Prerequisites

- Fly.io account (https://fly.io)
- `flyctl` CLI installed
- Docker installed locally

### Step 1: Install Flyctl

```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# Windows
choco install flyctl
```

### Step 2: Authenticate

```bash
flyctl auth login
```

### Step 3: Create App

```bash
flyctl apps create aegis-food-marketplace
```

### Step 4: Create Volumes

```bash
# Create persistent volumes for data
flyctl volumes create postgres_data --size 10 --region mad
flyctl volumes create redis_data --size 5 --region mad
flyctl volumes create cache_data --size 5 --region mad
```

### Step 5: Set Secrets

```bash
# Set all required secrets
flyctl secrets set SECRET_KEY=$(openssl rand -base64 32)
flyctl secrets set DATABASE_URL=postgresql://...
flyctl secrets set REDIS_URL=redis://...
flyctl secrets set SMTP_SERVER=smtp.gmail.com
flyctl secrets set SMTP_PORT=587
flyctl secrets set SMTP_USERNAME=your-email@gmail.com
flyctl secrets set SMTP_PASSWORD=your-gmail-app-password
flyctl secrets set SMTP_FROM_EMAIL=noreply@aegis-food.com

# List all secrets
flyctl secrets list
```

### Step 6: Configure Domain

```bash
# In Fly.io dashboard or via CLI:
flyctl ips list
# Add A and AAAA records to your DNS

# Or use Fly.io managed domains
flyctl certs create aegis-food.com
```

### Step 7: Deploy

```bash
# Deploy application
flyctl deploy

# Monitor deployment
flyctl status

# View logs
flyctl logs

# View recent deployments
flyctl releases
```

### Step 8: Configure Auto-scaling

The `fly.toml` file already includes auto-scaling configuration:

```bash
# View current scaling settings
flyctl scale show

# Manually scale if needed
flyctl scale count=2

# Update auto-scaling policy
flyctl autoscale set min=1 max=3
```

### Fly.io Management Commands

```bash
# View app status
flyctl status

# View detailed info
flyctl info

# Restart app
flyctl restart

# SSH into running instance
flyctl ssh console

# View logs
flyctl logs --lines=100
flyctl logs --follow

# Redeploy
flyctl deploy

# View deployment history
flyctl releases

# Rollback to previous version
flyctl releases rollback
```

---

## SSL/TLS Certificate Setup

### Let's Encrypt (Recommended - Free)

#### Automatic Setup (Nginx)

```bash
# Already handled by docker-compose setup
# Certificates stored in: deploy/ssl/

# Manual renewal
docker exec aegis-food-nginx-prod certbot renew
```

#### Manual Setup

```bash
# Create certificate
sudo certbot certonly --standalone \
  -d aegis-food.com \
  -d www.aegis-food.com \
  -d api.aegis-food.com

# Copy to deployment directory
sudo cp /etc/letsencrypt/live/aegis-food.com/fullchain.pem deploy/ssl/cert.pem
sudo cp /etc/letsencrypt/live/aegis-food.com/privkey.pem deploy/ssl/key.pem
sudo chown appuser:appuser deploy/ssl/*
```

### Commercial Certificates

1. Purchase from provider (DigiCert, Comodo, GlobalSign, etc.)
2. Generate CSR:
   ```bash
   openssl req -new -newkey rsa:2048 -nodes -out aegis-food.csr -keyout deploy/ssl/key.pem
   ```
3. Submit CSR to provider
4. Download certificate chain
5. Place in `deploy/ssl/cert.pem`

### Certificate Validation

```bash
# Check certificate expiry
openssl x509 -in deploy/ssl/cert.pem -text -noout | grep -A 2 "Validity"

# Test SSL configuration
openssl s_client -connect aegis-food.com:443 -tls1_2

# Verify with SSL Labs
# Visit: https://www.ssllabs.com/ssltest/analyze.html?d=aegis-food.com
```

---

## Database Backup & Recovery

### Automated Backups

```bash
# Create backup script
cat > /opt/aegis-food/backup-db.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/aegis-food/backups"
mkdir -p $BACKUP_DIR

# Daily backup with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/aegis-food_$TIMESTAMP.sql"

docker-compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U postgres aegis_food_prod > "$BACKUP_FILE"

# Compress backup
gzip "$BACKUP_FILE"

# Keep only last 30 days of backups
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_FILE.gz"
EOF

chmod +x /opt/aegis-food/backup-db.sh

# Add to crontab (runs daily at 2 AM)
crontab -e
# Add: 0 2 * * * /opt/aegis-food/backup-db.sh
```

### Manual Backup

```bash
# Using Docker Compose
docker-compose -f docker-compose.prod.yml exec db pg_dump -U postgres aegis_food_prod > backup.sql

# Compress
gzip backup.sql

# Upload to cloud storage (AWS S3, Google Cloud Storage, etc.)
# aws s3 cp backup.sql.gz s3://your-backup-bucket/
```

### Database Recovery

```bash
# Stop application
docker-compose -f docker-compose.prod.yml stop backend

# Restore from backup
gunzip backup.sql.gz
docker-compose -f docker-compose.prod.yml exec -T db \
  psql -U postgres aegis_food_prod < backup.sql

# Restart application
docker-compose -f docker-compose.prod.yml up -d backend

# Verify
curl https://aegis-food.com/health
```

### PostgreSQL Maintenance

```bash
# Connect to database
docker-compose -f docker-compose.prod.yml exec db psql -U postgres aegis_food_prod

# Inside psql:
# Analyze tables for query optimization
ANALYZE;

# Vacuum database (cleanup)
VACUUM FULL;

# List database size
\l+

# Check table sizes
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

# Exit
\q
```

---

## Monitoring & Logging

### Docker Compose Logging

```bash
# View real-time logs
docker-compose -f docker-compose.prod.yml logs -f

# View specific service logs
docker-compose -f docker-compose.prod.yml logs -f backend
docker-compose -f docker-compose.prod.yml logs -f db

# View last 100 lines
docker-compose -f docker-compose.prod.yml logs --tail=100 backend

# Save logs to file
docker-compose -f docker-compose.prod.yml logs > deployment.log
```

### Monitoring Tools

#### Prometheus + Grafana (Self-Hosted)

```bash
# Add to docker-compose.prod.yml:
# 
# prometheus:
#   image: prom/prometheus
#   volumes:
#     - ./deploy/prometheus.yml:/etc/prometheus/prometheus.yml
#     - prometheus_data:/prometheus
#
# grafana:
#   image: grafana/grafana
#   ports:
#     - "3000:3000"
#   volumes:
#     - grafana_data:/var/lib/grafana
```

#### External Monitoring Services

- **Datadog** - Application Performance Monitoring
- **New Relic** - APM and Infrastructure
- **Sentry** - Error tracking (Set `SENTRY_DSN`)
- **Honeycomb** - Observability
- **Scout APM** - Performance monitoring

### Health Checks

```bash
# Test API health
curl https://aegis-food.com/health

# Test database
curl -s https://aegis-food.com/health | jq .database

# Test connectivity
timeout 5 curl -v https://aegis-food.com/api/

# Check uptime
uptime
docker-compose -f docker-compose.prod.yml ps
```

---

## Troubleshooting

### Common Issues

#### 1. "Connection refused" on Database

```bash
# Check if database is running
docker-compose -f docker-compose.prod.yml ps db

# Check database logs
docker-compose -f docker-compose.prod.yml logs db

# Restart database
docker-compose -f docker-compose.prod.yml restart db

# Wait for health check
docker-compose -f docker-compose.prod.yml exec db pg_isready
```

#### 2. "502 Bad Gateway" from Nginx

```bash
# Check backend health
curl http://backend:8000/health

# Check backend logs
docker-compose -f docker-compose.prod.yml logs backend

# Restart backend
docker-compose -f docker-compose.prod.yml restart backend

# Check Nginx configuration
docker exec aegis-food-nginx-prod nginx -t
```

#### 3. High Memory Usage

```bash
# Check container memory usage
docker stats

# Check specific container
docker stats aegis-food-backend-prod

# Restart container
docker-compose -f docker-compose.prod.yml restart backend

# Increase memory limit in docker-compose.prod.yml
```

#### 4. "Permission denied" Errors

```bash
# Check file permissions
ls -la /opt/aegis-food/deploy/ssl/

# Fix permissions
sudo chown -R aegis:aegis /opt/aegis-food
sudo chmod 600 /opt/aegis-food/.env.prod
```

#### 5. Email Not Sending

```bash
# Verify SMTP settings
echo | openssl s_client -connect smtp.gmail.com:587 -starttls smtp

# Check Docker logs
docker-compose -f docker-compose.prod.yml logs backend | grep -i smtp

# Test with environment variables
docker-compose -f docker-compose.prod.yml exec backend \
  python -c "import os; print(os.getenv('SMTP_SERVER'))"
```

### Debug Commands

```bash
# Access running container
docker-compose -f docker-compose.prod.yml exec backend bash

# Run Python commands in container
docker-compose -f docker-compose.prod.yml exec backend python -c "..."

# Check environment variables
docker-compose -f docker-compose.prod.yml exec backend env | grep -i secret

# Monitor system resources
docker stats
docker system df

# Clean up old images/containers
docker system prune -a --volumes
```

---

## Post-Deployment Steps

### 1. Create Admin User

```bash
# Via API
curl -X POST https://aegis-food.com/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@aegis-food.com",
    "password": "secure-password",
    "empresa_id": 1,
    "nombre_empresa": "AEGIS-FOOD",
    "rol": "admin"
  }'
```

### 2. Verify API Endpoints

```bash
# Get documentation
curl https://aegis-food.com/docs

# Test authentication
curl -X POST https://aegis-food.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@aegis-food.com", "password": "password"}'

# List available endpoints
curl https://aegis-food.com/openapi.json | jq .paths
```

### 3. Setup Monitoring Alerts

- Configure uptime monitoring (Pingdom, Uptime Robot)
- Set up log aggregation (CloudWatch, Loggly, Splunk)
- Configure alerting for errors and performance issues
- Set up on-call rotation

### 4. Document Access Credentials

Create a secure document with:
- Admin credentials (encrypted)
- Database backups location
- SSL certificate renewal procedure
- Emergency contacts
- Disaster recovery playbook

### 5. Load Testing

```bash
# Install Apache Bench
apt-get install apache2-utils

# Run load test
ab -n 1000 -c 10 https://aegis-food.com/health

# Or use wrk for more detailed results
apt-get install wrk
wrk -t4 -c100 -d30s https://aegis-food.com/health
```

### 6. Security Hardening Checklist

- [ ] Disable root login
- [ ] Configure firewall (UFW)
- [ ] Set up fail2ban
- [ ] Enable automatic security updates
- [ ] Configure SSH key-based authentication only
- [ ] Setup VPN for admin access
- [ ] Enable audit logging
- [ ] Regular security scans (Trivy, Snyk)

### 7. Documentation

- [ ] Update deployment documentation
- [ ] Document custom configurations
- [ ] Create runbooks for common tasks
- [ ] Document recovery procedures
- [ ] Create architecture diagrams

---

## Support & Resources

- **GitHub Issues**: Report bugs and features
- **Documentation**: See README.md
- **API Docs**: Available at `/docs` endpoint
- **Community**: Discuss on GitHub Discussions

---

## Next Steps

1. Set up monitoring and alerting
2. Configure backup schedule
3. Plan capacity scaling
4. Schedule security audit
5. Set up CI/CD pipeline
6. Train operations team
7. Create incident response procedures

---

**Last Updated**: 2025-04-12
**Version**: 1.0
**Maintained By**: AEGIS-FOOD Development Team
