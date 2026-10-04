from flask import Blueprint, render_template, g, abort, request, redirect, url_for, flash
from auth import role_required
from db import query_one, query_all, execute
from utils.helpers import now_iso, log_audit, notify, generate_record_number
from utils.state_machine import assert_transition, InvalidTransitionError

bp = Blueprint("provider", __name__, url_prefix="/provider")


def get_current_provider():
    """Look up the service_providers row owned by the logged-in provider user."""
    return query_one("SELECT * FROM service_providers WHERE owner_user_id = ?", (g.user["id"],))


def require_provider():
    provider = get_current_provider()
    if provider is None:
        abort(403)
    return provider


@bp.route("/dashboard")
@role_required("provider")
def dashboard():
    provider = require_provider()
    pid = provider["id"]

    def count(status_clause, params=()):
        return query_one(
            f"SELECT COUNT(*) c FROM service_records WHERE provider_id = ? AND {status_clause}",
            (pid,) + params,
        )["c"]

    stats = {
        "new_requests": query_one(
            "SELECT COUNT(*) c FROM service_requests WHERE provider_id = ? AND status = 'PENDING'", (pid,)
        )["c"],
        "in_progress": count("status = 'SERVICE_IN_PROGRESS'"),
        "ready_for_return": count("status = 'READY_FOR_RETURN'"),
        "pending_payments": count("status = 'PAYMENT_PENDING'"),
        "pending_returns": count("status = 'RETURN_PENDING'"),
        "open_disputes": count("status = 'DISPUTED'"),
        "completed": count("status = 'COMPLETED'"),
        "received": count(
            "status IN ('HANDOVER_PENDING','HANDOVER_VERIFIED','SERVICE_IN_PROGRESS','SERVICE_COMPLETED','PAYMENT_PENDING')"
        ),
    }
    recent = query_all(
        """SELECT sr.*, u.name AS customer_name FROM service_records sr
           JOIN users u ON u.id = sr.customer_id
           WHERE sr.provider_id = ? ORDER BY sr.created_at DESC LIMIT 10""",
        (pid,),
    )
    return render_template("provider/dashboard.html", provider=provider, stats=stats, recent=recent)


@bp.route("/requests")
@role_required("provider")
def requests_list():
    provider = require_provider()
    pending = query_all(
        """SELECT sq.*, u.name AS customer_name FROM service_requests sq
           JOIN users u ON u.id = sq.customer_id
           WHERE sq.provider_id = ? AND sq.status = 'PENDING' ORDER BY sq.created_at DESC""",
        (provider["id"],),
    )
    handled = query_all(
        """SELECT sq.*, u.name AS customer_name FROM service_requests sq
           JOIN users u ON u.id = sq.customer_id
           WHERE sq.provider_id = ? AND sq.status != 'PENDING' ORDER BY sq.created_at DESC LIMIT 20""",
        (provider["id"],),
    )
    return render_template("provider/requests.html", pending=pending, handled=handled)


@bp.route("/requests/<int:request_id>/accept", methods=["POST"])
@role_required("provider")
def accept_request(request_id):
    provider = require_provider()
    req = query_one(
        "SELECT * FROM service_requests WHERE id = ? AND provider_id = ?",
        (request_id, provider["id"]),
    )
    if req is None:
        abort(404)
    if req["status"] != "PENDING":
        flash("This request has already been handled.", "error")
        return redirect(url_for("provider.requests_list"))

    execute("UPDATE service_requests SET status = 'ACCEPTED' WHERE id = ?", (request_id,))

    record_number = generate_record_number()
    ts = now_iso()
    record_id = execute(
        """INSERT INTO service_records
           (service_request_id, customer_id, provider_id, record_number, item_name, brand, model,
            serial_number, problem_description, estimated_cost, expected_completion_date,
            status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'DRAFT', ?)""",
        (req["id"], req["customer_id"], provider["id"], record_number, req["item_name"],
         req["brand"], req["model"], req["serial_number"], req["problem_description"],
         req["expected_completion_date"], ts),
    )
    log_audit(record_id, g.user["id"], "REQUEST_ACCEPTED", "PENDING", "ACCEPTED")
    log_audit(record_id, g.user["id"], "SERVICE_RECORD_CREATED", None, record_number)

    # Move straight into the handover-documentation stage.
    assert_transition("DRAFT", "HANDOVER_PENDING")
    execute("UPDATE service_records SET status = 'HANDOVER_PENDING' WHERE id = ?", (record_id,))
    log_audit(record_id, g.user["id"], "STATUS_CHANGED", "DRAFT", "HANDOVER_PENDING")

    notify(req["customer_id"], "Your service request was accepted.",
           f"{provider['business_name']} accepted your request for {req['item_name']}. "
           f"Record {record_number} has been created.", record_id)

    flash(f"Request accepted. Service record {record_number} created.", "success")
    return redirect(url_for("records.view_record", record_number=record_number))


@bp.route("/requests/<int:request_id>/reject", methods=["POST"])
@role_required("provider")
def reject_request(request_id):
    provider = require_provider()
    req = query_one(
        "SELECT * FROM service_requests WHERE id = ? AND provider_id = ?",
        (request_id, provider["id"]),
    )
    if req is None:
        abort(404)
    if req["status"] != "PENDING":
        flash("This request has already been handled.", "error")
        return redirect(url_for("provider.requests_list"))

    execute("UPDATE service_requests SET status = 'REJECTED' WHERE id = ?", (request_id,))
    log_audit(None, g.user["id"], "REQUEST_REJECTED", "PENDING", "REJECTED")
    notify(req["customer_id"], "Your service request was declined.",
           f"{provider['business_name']} was unable to accept your request for {req['item_name']}.")
    flash("Request rejected.", "success")
    return redirect(url_for("provider.requests_list"))


@bp.route("/active-services")
@role_required("provider")
def active_services():
    provider = require_provider()
    records = query_all(
        """SELECT sr.*, u.name AS customer_name FROM service_records sr
           JOIN users u ON u.id = sr.customer_id
           WHERE sr.provider_id = ? AND sr.status NOT IN ('COMPLETED','CANCELLED')
           ORDER BY sr.created_at DESC""",
        (provider["id"],),
    )
    return render_template("provider/active_services.html", records=records)


@bp.route("/returns")
@role_required("provider")
def returns_list():
    provider = require_provider()
    records = query_all(
        """SELECT sr.*, u.name AS customer_name FROM service_records sr
           JOIN users u ON u.id = sr.customer_id
           WHERE sr.provider_id = ? AND sr.status IN ('READY_FOR_RETURN','RETURN_PENDING','RETURN_VERIFIED')
           ORDER BY sr.created_at DESC""",
        (provider["id"],),
    )
    return render_template("provider/returns.html", records=records)


@bp.route("/disputes")
@role_required("provider")
def disputes_list():
    provider = require_provider()
    disputes = query_all(
        """SELECT d.*, sr.record_number, sr.item_name FROM disputes d
           JOIN service_records sr ON sr.id = d.service_record_id
           WHERE sr.provider_id = ? ORDER BY d.created_at DESC""",
        (provider["id"],),
    )
    return render_template("provider/disputes.html", disputes=disputes)


@bp.route("/profile")
@role_required("provider")
def profile():
    provider = require_provider()
    return render_template("provider/profile.html", provider=provider)


@bp.route("/notifications")
@role_required("provider")
def notifications():
    items = query_all(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
        (g.user["id"],),
    )
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (g.user["id"],))
    return render_template("provider/notifications.html", items=items)
