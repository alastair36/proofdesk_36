"""
Central place for every writable location in ProofDesk.

Locally  -> data lives inside the project (instance/, static/uploads, static/qr).
Vercel   -> the project directory is READ-ONLY, only /tmp is writable, so all
            runtime data (SQLite DB, uploaded photos, QR codes) goes there.
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("PROOFDESK_SERVERLESS"))

if IS_SERVERLESS:
    DATA_DIR = os.path.join(os.environ.get("TMPDIR", "/tmp"), "proofdesk")
    DB_PATH = os.path.join(DATA_DIR, "proofdesk.db")
    UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
    QR_DIR = os.path.join(DATA_DIR, "qr")
else:
    DATA_DIR = PROJECT_ROOT
    DB_PATH = os.path.join(PROJECT_ROOT, "instance", "proofdesk.db")
    UPLOAD_DIR = os.path.join(PROJECT_ROOT, "static", "uploads")
    QR_DIR = os.path.join(PROJECT_ROOT, "static", "qr")

# Vercel rejects request bodies above ~4.5 MB before they reach the app.
MAX_UPLOAD_BYTES = (4 if IS_SERVERLESS else 5) * 1024 * 1024
