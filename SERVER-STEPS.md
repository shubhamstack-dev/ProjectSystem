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

---

## v1.5 par update karne se pehle (ek baar)

1. `.env` me SECRET_KEY daalo. Iske bina har restart par sab log sign out ho jaate
   hain aur khule video links toot jaate hain:

       cd /opt/projectsystem
       echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env

   Ye key ek baar banao aur phir kabhi mat badlo.

2. Update:

       git pull && docker compose -f docker-compose.prod.yml up -d --build

   Database ke naye columns API start hote hi apne aap ban jaate hain.
   Purane attachments (database me rakhe hue) waise hi khulte rahenge.

## Uploaded files (screenshots, videos) kahan hain

Ab files database me nahi, `attachments` volume me disk par rehti hain.
Database me sirf list hai, files volume me hain - **backup dono ka lena hai**:

    # database (pehle jaisa)
    docker compose -f docker-compose.prod.yml exec mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" projectsystem' > backup-$(date +%F).sql

    # files (naya)
    docker compose -f docker-compose.prod.yml exec -T backend tar czf - -C /app/data attachments > attachments-$(date +%F).tgz

Dono files `.gitignore` me hain - inhe kabhi commit mat karna. v1.3 ke baad
database backup me password hashes hote hain.

Restore:

    docker compose -f docker-compose.prod.yml exec -T backend tar xzf - -C /app/data < attachments-YYYY-MM-DD.tgz

## Disk space

Video badi hoti hain (250 MB tak ek file). Disk dekhte raho:

    df -h /
    docker system df -v | grep attachments
