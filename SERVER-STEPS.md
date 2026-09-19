# VPS par host karne ke steps (Ubuntu VPS, Docker)

Files jo repo me add karni hain (is zip se):
  docker-compose.prod.yml, .env.prod.example          -> repo root
  frontend/Dockerfile.prod, frontend/Caddyfile, frontend/.dockerignore
  backend/.dockerignore

Server par (SSH se):
  ssh root@103.17.193.174
  curl -fsSL https://get.docker.com | sh
  apt install -y git ufw
  ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable
  git clone https://github.com/shubhamstack-dev/ProjectSystem.git /opt/projectsystem
  cd /opt/projectsystem
  cp .env.prod.example .env && nano .env        # DOMAIN + strong password
  docker compose -f docker-compose.prod.yml up -d --build
  docker compose -f docker-compose.prod.yml exec backend python seed.py   # optional demo data

Update karne par:
  cd /opt/projectsystem && git pull && docker compose -f docker-compose.prod.yml up -d --build

Backup:
  docker compose -f docker-compose.prod.yml exec mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" projectsystem' > backup-$(date +%F).sql
