import secrets
import string
from datetime import datetime, timezone
from db import execute, query_one


def now_iso():
    """Server-generated timestamp. Never trust a client-supplied timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def generate_record_number():
    """SR-YYYY-XXXXX, server-generated, never client-supplied."""
    year = datetime.now(timezone.utc).year
    while True:
        suffix = "".join(secrets.choice(string.digits) for _ in range(5))
        candidate = f"SR-{year}-{suffix}"
        exists = query_one("SELECT id FROM service_records WHERE record_number = ?", (candidate,))
        if not exists:
            return candidate


def generate_code(length=10):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def log_audit(service_record_id, user_id, action, old_value=None, new_value=None):
    execute(
        """INSERT INTO audit_logs (service_record_id, user_id, action, old_value, new_value, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (service_record_id, user_id, action, old_value, new_value, now_iso()),
    )


def notify(user_id, title, message, service_record_id=None):
    execute(
        """INSERT INTO notifications (user_id, title, message, service_record_id, is_read, created_at)
           VALUES (?, ?, ?, ?, 0, ?)""",
        (user_id, title, message, service_record_id, now_iso()),
    )
