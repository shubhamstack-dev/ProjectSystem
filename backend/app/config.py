import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost:3306/projectsystem")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

# ---------------------------------------------------------------- v1.3 auth
# Signing key for the bearer tokens this API issues. Generated per process when
# unset, which means restarting the API signs everyone out — acceptable in
# development, so set it in .env for anything real.
SECRET_KEY = os.getenv("SECRET_KEY") or ""
if not SECRET_KEY:
    SECRET_KEY = os.urandom(32).hex()
    print("[startup] WARNING: SECRET_KEY is not set. A temporary one is in use, so every "
          "restart will sign everyone out and break open attachment links. Set SECRET_KEY "
          "in the environment.", flush=True)
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))

# Microsoft Entra ID (Azure AD). Leave blank and the product runs on local
# accounts only; the sign-in screen then says so rather than offering a button
# that cannot work.
ENTRA_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "").strip()
ENTRA_CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "").strip()
ENTRA_CLIENT_SECRET = os.getenv("ENTRA_CLIENT_SECRET", "").strip()
# Where Microsoft sends the browser back to. Must match the app registration.
ENTRA_REDIRECT_URI = os.getenv("ENTRA_REDIRECT_URI",
                               "http://localhost:5173/auth/callback").strip()
# Which organisation and role an imported user is filed under. Members are
# Aequm India staff; Guests are customers invited into the tenant as B2B.
ENTRA_MEMBER_ORG = os.getenv("ENTRA_MEMBER_ORG", "Aequm India").strip()
ENTRA_MEMBER_ROLE = os.getenv("ENTRA_MEMBER_ROLE", "Team Member").strip()
ENTRA_GUEST_ORG = os.getenv("ENTRA_GUEST_ORG", "Customer").strip()
ENTRA_GUEST_ROLE = os.getenv("ENTRA_GUEST_ROLE", "Customer Contact").strip()
# Sign-in without a prior import: allowed for Members, refused for Guests
# unless an administrator has imported them. A customer who can invent an
# account for themselves is a customer who can see another customer's tickets.
ENTRA_AUTO_PROVISION_MEMBERS = os.getenv("ENTRA_AUTO_PROVISION_MEMBERS", "1") == "1"
ENTRA_AUTO_PROVISION_GUESTS = os.getenv("ENTRA_AUTO_PROVISION_GUESTS", "0") == "1"

# ---------------------------------------------------------------- v1.5 files
# Attachments live on disk, not in the database. A phone video is 50-200 MB;
# MySQL's MEDIUMBLOB stops at 16 MB and every byte would travel through
# max_allowed_packet and the backup. The database keeps only the metadata.
ATTACHMENT_DIR = os.getenv("ATTACHMENT_DIR", os.path.join(os.getcwd(), "data", "attachments"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "25"))       # images and documents
MAX_VIDEO_MB = int(os.getenv("MAX_VIDEO_MB", "250"))    # screen recordings, phone video
MAX_FILES_PER_CALL = int(os.getenv("MAX_FILES_PER_CALL", "10"))
# How long a signed attachment link stays valid. Long enough to watch a video,
# short enough that a copied link is not a permanent key.
ATTACHMENT_LINK_MINUTES = int(os.getenv("ATTACHMENT_LINK_MINUTES", "60"))
