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

---

## v1.6: Email (SMTP bhejne ke liye, IMAP padhne ke liye)

Update ke baad admin se login karo -> **Email** screen. Wahan server details bharo;
kuch bhi `.env` me nahi daalna. Passwords SECRET_KEY se encrypt hoke database me
rehte hain - isliye SECRET_KEY kabhi mat badlo, warna mail password dobara daalna padega.

Microsoft 365 ke liye:
- Mailbox par **SMTP AUTH** on karna padta hai (Microsoft 365 admin centre ->
  user -> Mail -> Manage email apps -> Authenticated SMTP).
- MFA wale account ke liye **app password** chahiye, normal password nahi chalega.
- "Send test" button se turant pata chal jaata hai ki setting sahi hai ya nahi.

Server ke firewall me outgoing port 587 (ya 465) aur 993 khule hone chahiye:

    ufw allow out 587 && ufw allow out 465 && ufw allow out 993

Reply-To me wahi mailbox daalo jo IMAP me padha ja raha hai - tabhi customer ka
email reply ticket par wapas aayega.

## v1.6.1: Microsoft 365 mail bina password ke (OAuth / XOAUTH2)

Microsoft 365 par IMAP ke liye password login band hai aur SMTP AUTH bhi band ho
raha hai. Isliye Email screen me **Authentication = Microsoft 365 (OAuth)** chuno.
Ye wahi App Registration use karta hai jo "Sign in with Microsoft" ke liye hai
(.env ke ENTRA_TENANT_ID / ENTRA_CLIENT_ID / ENTRA_CLIENT_SECRET). Ek baar ye
teen kaam Azure/Exchange me:

### 1. App ko mail permissions do (Azure Portal)
Entra ID -> App registrations -> apna app -> **API permissions** -> Add a permission
-> **APIs my organization uses** -> search "Office 365 Exchange Online" -> **Application permissions**:
- `IMAP.AccessAsApp`  (replies padhne ke liye)
- `SMTP.SendAsApp`    (bhejne ke liye)
Add, phir **Grant admin consent for <tenant>**. Status green "Granted" hona chahiye.

### 2. Exchange me app ko mailbox par access do (PowerShell, ek baar, admin)
Windows PowerShell (Admin) me:

    Install-Module ExchangeOnlineManagement -Scope CurrentUser
    Connect-ExchangeOnline

Azure Portal se do IDs lo: App registration ke **Overview** me "Application (client) ID"
aur **Enterprise applications** me usi app ka "Object ID" (ye alag hota hai).

    New-ServicePrincipal -AppId <Application (client) ID> -ObjectId <Enterprise app Object ID> -DisplayName "ProjectSystem mail"
    Add-MailboxPermission -Identity Alok.Jayant@aequmindia.in -User <Application (client) ID> -AccessRights FullAccess

(Add-MailboxPermission me -User me client ID hi jaata hai. Agar "already exists"
aaye to pehli command skip karo.) Propagate hone me 15-30 minute lag sakte hain.

### 3. Email screen
- SMTP: Authentication = Microsoft 365 (OAuth), User = mailbox (Alok.Jayant@aequmindia.in),
  From address = wahi. Password field gayab ho jayega. **Send test**.
- IMAP: checkbox on, Authentication = Microsoft 365 (OAuth), Mailbox user = wahi,
  Server outlook.office365.com, 993. **Test the mailbox**.
- Reply-To = wahi mailbox.
- Neeche "Microsoft 365 app (OAuth)" panel khali chhod sakte ho (.env se lega),
  ya alag app use karni ho to wahan bharo.

Errors:
- "Microsoft refused to issue a mail token ... AADSTS7000215" -> client secret galat/expired.
- "the mailbox refused it" -> step 1 (consent) ya step 2 (mailbox permission) adhoora,
  ya abhi propagate nahi hua.
