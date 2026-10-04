from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from auth import role_required
from db import query_one, query_all, execute
from utils.helpers import now_iso, log_audit, notify
from utils.state_machine import ALLOWED_TRANSITIONS

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/dashboard")
@role_required("admin")
def dashboard():
    def count(sql, params=()):
        return query_one(sql, params)["c"]

    stats = {
        "total_users": count("SELECT COUNT(*) c FROM users WHERE role != 'admin'"),
        "total_providers": count("SELECT COUNT(*) c FROM service_providers"),
        "active_records": count(
            "SELECT COUNT(*) c FROM service_records WHERE status NOT IN ('COMPLETED','CANCELLED','DRAFT')"
        ),
        "completed_services": count("SELECT COUNT(*) c FROM service_records WHERE status = 'COMPLETED'"),
        "pending_handovers": count("SELECT COUNT(*) c FROM service_records WHERE status = 'HANDOVER_PENDING'"),
        "pending_returns": count("SELECT COUNT(*) c FROM service_records WHERE status IN ('READY_FOR_RETURN','RETURN_PENDING')"),
        "open_disputes": count("SELECT COUNT(*) c FROM disputes WHERE status != 'CLOSED'"),
        "closed_disputes": count("SELECT COUNT(*) c FROM disputes WHERE status = 'CLOSED'"),
    }

    by_category = query_all(
        "SELECT category, COUNT(*) c FROM service_requests GROUP BY category ORDER BY c DESC"
    )
    by_status = query_all(
        "SELECT status, COUNT(*) c FROM service_records GROUP BY status"
    )
    disputes_by_category = query_all(
        "SELECT category, COUNT(*) c FROM disputes GROUP BY category ORDER BY c DESC"
    )
    monthly = query_all(
        """SELECT substr(created_at,1,7) AS ym, COUNT(*) c FROM service_records
           GROUP BY ym ORDER BY ym"""
    )
    return render_template(
        "admin/dashboard.html", stats=stats, by_category=by_category, by_status=by_status,
        disputes_by_category=disputes_by_category, monthly=monthly,
    )


@bp.route("/users")
@role_required("admin")
def users_list():
    q = request.args.get("q", "").strip()
    if q:
        users = query_all(
            """SELECT * FROM users WHERE role != 'admin' AND
               (name LIKE ? OR email LIKE ?) ORDER BY created_at DESC""",
            (f"%{q}%", f"%{q}%"),
        )
    else:
        users = query_all("SELECT * FROM users WHERE role != 'admin' ORDER BY created_at DESC")
    return render_template("admin/users.html", users=users, q=q)


@bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@role_required("admin")
def suspend_user(user_id):
    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if user is None or user["role"] == "admin":
        abort(404)
    execute("UPDATE users SET status = 'suspended' WHERE id = ?", (user_id,))
    log_audit(None, g.user["id"], "USER_SUSPENDED", "active", f"user #{user_id}")
    flash(f"{user['name']} has been suspended.", "success")
    return redirect(url_for("admin.users_list"))


@bp.route("/users/<int:user_id>/reactivate", methods=["POST"])
@role_required("admin")
def reactivate_user(user_id):
    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if user is None or user["role"] == "admin":
        abort(404)
    execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
    log_audit(None, g.user["id"], "USER_REACTIVATED", "suspended", f"user #{user_id}")
    flash(f"{user['name']} has been reactivated.", "success")
    return redirect(url_for("admin.users_list"))


@bp.route("/providers")
@role_required("admin")
def providers_list():
    providers = query_all(
        """SELECT sp.*, u.name AS owner_name, u.email AS owner_email, u.status AS owner_status
           FROM service_providers sp JOIN users u ON u.id = sp.owner_user_id
           ORDER BY sp.created_at DESC"""
    )
    return render_template("admin/providers.html", providers=providers)


@bp.route("/providers/<int:provider_id>/<action>", methods=["POST"])
@role_required("admin")
def provider_action(provider_id, action):
    if action not in ("verify", "reject", "suspend"):
        abort(404)
    provider = query_one("SELECT * FROM service_providers WHERE id = ?", (provider_id,))
    if provider is None:
        abort(404)
    new_status = {"verify": "VERIFIED", "reject": "REJECTED", "suspend": "SUSPENDED"}[action]
    execute("UPDATE service_providers SET verification_status = ? WHERE id = ?", (new_status, provider_id))
    log_audit(None, g.user["id"], "PROVIDER_STATUS_CHANGED", provider["verification_status"], new_status)
    notify(provider["owner_user_id"], "Business verification update",
           f"Your business '{provider['business_name']}' status is now {new_status}.")
    flash(f"Provider set to {new_status}.", "success")
    return redirect(url_for("admin.providers_list"))


@bp.route("/services")
@role_required("admin")
def services_list():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    sql = """SELECT sr.*, sp.business_name, u.name AS customer_name FROM service_records sr
             JOIN service_providers sp ON sp.id = sr.provider_id
             JOIN users u ON u.id = sr.customer_id WHERE 1=1"""
    params = []
    if q:
        sql += " AND (sr.record_number LIKE ? OR sr.item_name LIKE ? OR sr.brand LIKE ? OR sr.model LIKE ? OR u.name LIKE ? OR sp.business_name LIKE ?)"
        params += [f"%{q}%"] * 6
    if status:
        sql += " AND sr.status = ?"
        params.append(status)
    sql += " ORDER BY sr.created_at DESC LIMIT 200"
    records = query_all(sql, tuple(params))
    return render_template("admin/services.html", records=records, q=q, status=status)


@bp.route("/disputes")
@role_required("admin")
def disputes_list():
    disputes = query_all(
        """SELECT d.*, sr.record_number, sr.item_name, u.name AS opened_by_name
           FROM disputes d JOIN service_records sr ON sr.id = d.service_record_id
           JOIN users u ON u.id = d.opened_by ORDER BY d.created_at DESC"""
    )
    return render_template("admin/disputes.html", disputes=disputes)


@bp.route("/disputes/<int:dispute_id>")
@role_required("admin")
def dispute_detail(dispute_id):
    dispute = query_one(
        """SELECT d.*, sr.record_number, u.name AS opened_by_name FROM disputes d
           JOIN service_records sr ON sr.id = d.service_record_id
           JOIN users u ON u.id = d.opened_by WHERE d.id = ?""",
        (dispute_id,),
    )
    if dispute is None:
        abort(404)
    record = query_one(
        """SELECT sr.*, sp.business_name, u.name AS customer_name FROM service_records sr
           JOIN service_providers sp ON sp.id = sr.provider_id
           JOIN users u ON u.id = sr.customer_id WHERE sr.id = ?""",
        (dispute["service_record_id"],),
    )
    accessories = query_all("SELECT * FROM accessories WHERE service_record_id=?", (record["id"],))
    conditions = query_all("SELECT * FROM condition_reports WHERE service_record_id=?", (record["id"],))
    evidence = query_all("SELECT * FROM evidence_files WHERE service_record_id=?", (record["id"],))
    confirmations = query_all("SELECT * FROM confirmations WHERE service_record_id=?", (record["id"],))
    service_updates = query_all(
        """SELECT su.*, u.name AS created_by_name FROM service_updates su
           JOIN users u ON u.id = su.created_by WHERE su.service_record_id=? ORDER BY su.created_at""",
        (record["id"],),
    )
    payments = query_all("SELECT * FROM payments WHERE service_record_id=?", (record["id"],))
    return_row = query_one("SELECT * FROM returns WHERE service_record_id=?", (record["id"],))
    audit_logs = query_all(
        """SELECT al.*, u.name AS user_name FROM audit_logs al LEFT JOIN users u ON u.id = al.user_id
           WHERE al.service_record_id=? ORDER BY al.created_at""",
        (record["id"],),
    )
    return render_template(
        "admin/dispute_detail.html", dispute=dispute, record=record, accessories=accessories,
        conditions=conditions, evidence=evidence, confirmations=confirmations,
        service_updates=service_updates, payments=payments, return_row=return_row, audit_logs=audit_logs,
    )


@bp.route("/disputes/<int:dispute_id>/resolve", methods=["POST"])
@role_required("admin")
def resolve_dispute(dispute_id):
    dispute = query_one("SELECT * FROM disputes WHERE id = ?", (dispute_id,))
    if dispute is None:
        abort(404)
    if dispute["status"] == "CLOSED":
        flash("This dispute is already closed.", "error")
        return redirect(url_for("admin.dispute_detail", dispute_id=dispute_id))

    resolution = request.form.get("resolution", "").strip()
    if not resolution:
        flash("Please enter a resolution note.", "error")
        return redirect(url_for("admin.dispute_detail", dispute_id=dispute_id))

    ts = now_iso()
    execute(
        "UPDATE disputes SET status='CLOSED', resolution=?, closed_at=? WHERE id=?",
        (resolution, ts, dispute_id),
    )
    record = query_one(
        """SELECT sr.*, sp.owner_user_id AS provider_owner_id FROM service_records sr
           JOIN service_providers sp ON sp.id = sr.provider_id WHERE sr.id = ?""",
        (dispute["service_record_id"],),
    )
    restore_to = dispute["previous_status"] or "COMPLETED"
    if restore_to in ALLOWED_TRANSITIONS.get("DISPUTED", set()):
        execute("UPDATE service_records SET status=? WHERE id=?", (restore_to, record["id"]))
        log_audit(record["id"], g.user["id"], "STATUS_CHANGED", "DISPUTED", restore_to)

    log_audit(record["id"], g.user["id"], "DISPUTE_CLOSED", "OPEN", "CLOSED")
    notify(dispute["opened_by"], "Your dispute has been resolved.",
           f"Resolution: {resolution}", record["id"])
    notify(record["provider_owner_id"], "Dispute resolved.", f"Resolution: {resolution}", record["id"])
    flash("Dispute resolved and closed.", "success")
    return redirect(url_for("admin.dispute_detail", dispute_id=dispute_id))


@bp.route("/audit-logs")
@role_required("admin")
def audit_logs():
    logs = query_all(
        """SELECT al.*, u.name AS user_name, sr.record_number FROM audit_logs al
           LEFT JOIN users u ON u.id = al.user_id
           LEFT JOIN service_records sr ON sr.id = al.service_record_id
           ORDER BY al.created_at DESC LIMIT 300"""
    )
    return render_template("admin/audit_logs.html", logs=logs)
