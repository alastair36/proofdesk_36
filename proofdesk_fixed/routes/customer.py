from flask import Blueprint, render_template, g, request, redirect, url_for, flash, abort
from auth import role_required
from db import query_all, query_one, execute
from utils.helpers import now_iso, log_audit, notify

bp = Blueprint("customer", __name__, url_prefix="/customer")

CATEGORIES = [
    "Electronics", "Laptop/Desktop", "Mobile Phone", "Appliance", "Clothing/Laundry",
    "Shoes", "Watch", "Furniture", "Vehicle-related", "Other",
]

ACTIVE_RECORD_STATUSES = (
    "HANDOVER_PENDING", "HANDOVER_VERIFIED", "SERVICE_IN_PROGRESS",
    "SERVICE_COMPLETED", "PAYMENT_PENDING",
)


@bp.route("/dashboard")
@role_required("customer")
def dashboard():
    uid = g.user["id"]
    active = query_all(
        """SELECT sr.*, sp.business_name FROM service_records sr
           JOIN service_providers sp ON sp.id = sr.provider_id
           WHERE sr.customer_id = ? AND sr.status IN
           ('HANDOVER_PENDING','HANDOVER_VERIFIED','SERVICE_IN_PROGRESS','SERVICE_COMPLETED','PAYMENT_PENDING')
           ORDER BY sr.created_at DESC""",
        (uid,),
    )
    awaiting_confirmation = [
        r for r in active
        if r["status"] == "HANDOVER_PENDING"
        and not query_one(
            "SELECT id FROM confirmations WHERE service_record_id=? AND role='customer' AND confirmation_type='HANDOVER'",
            (r["id"],),
        )
    ]
    under_service = [r for r in active if r["status"] == "SERVICE_IN_PROGRESS"]
    ready_pickup = query_all(
        """SELECT sr.*, sp.business_name FROM service_records sr
           JOIN service_providers sp ON sp.id = sr.provider_id
           WHERE sr.customer_id = ? AND sr.status IN ('READY_FOR_RETURN','RETURN_PENDING')
           ORDER BY sr.created_at DESC""",
        (uid,),
    )
    completed = query_all(
        """SELECT sr.*, sp.business_name FROM service_records sr
           JOIN service_providers sp ON sp.id = sr.provider_id
           WHERE sr.customer_id = ? AND sr.status = 'COMPLETED'
           ORDER BY sr.created_at DESC""",
        (uid,),
    )
    disputes = query_all(
        """SELECT d.*, sr.record_number FROM disputes d
           JOIN service_records sr ON sr.id = d.service_record_id
           WHERE sr.customer_id = ? AND d.status != 'CLOSED'
           ORDER BY d.created_at DESC""",
        (uid,),
    )
    pending_requests = query_all(
        """SELECT sq.*, sp.business_name FROM service_requests sq
           JOIN service_providers sp ON sp.id = sq.provider_id
           WHERE sq.customer_id = ? AND sq.status = 'PENDING' ORDER BY sq.created_at DESC""",
        (uid,),
    )
    return render_template(
        "customer/dashboard.html",
        active=active, awaiting_confirmation=awaiting_confirmation,
        under_service=under_service, ready_pickup=ready_pickup,
        completed=completed, disputes=disputes, pending_requests=pending_requests,
    )


@bp.route("/requests")
@role_required("customer")
def requests_list():
    reqs = query_all(
        """SELECT sq.*, sp.business_name FROM service_requests sq
           JOIN service_providers sp ON sp.id = sq.provider_id
           WHERE sq.customer_id = ? ORDER BY sq.created_at DESC""",
        (g.user["id"],),
    )
    return render_template("customer/requests.html", requests=reqs)


@bp.route("/requests/new", methods=["GET", "POST"])
@role_required("customer")
def new_request():
    providers = query_all(
        "SELECT * FROM service_providers WHERE verification_status = 'VERIFIED' ORDER BY business_name"
    )
    if request.method == "POST":
        errors = []
        provider_id = request.form.get("provider_id", "")
        category = request.form.get("category", "").strip()
        item_name = request.form.get("item_name", "").strip()
        brand = request.form.get("brand", "").strip()
        model = request.form.get("model", "").strip()
        serial_number = request.form.get("serial_number", "").strip()
        problem_description = request.form.get("problem_description", "").strip()
        preferred_service = request.form.get("preferred_service", "").strip()
        expected_completion_date = request.form.get("expected_completion_date", "").strip()
        additional_notes = request.form.get("additional_notes", "").strip()

        provider = query_one(
            "SELECT * FROM service_providers WHERE id = ? AND verification_status = 'VERIFIED'",
            (provider_id,),
        ) if provider_id else None

        if not provider:
            errors.append("Please select a valid, verified service provider.")
        if category not in CATEGORIES:
            errors.append("Please select a valid category.")
        if not item_name:
            errors.append("Item name is required.")
        if not problem_description:
            errors.append("Problem description is required.")
        if expected_completion_date:
            try:
                from datetime import date
                date.fromisoformat(expected_completion_date)
            except ValueError:
                errors.append("Expected completion date is invalid.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("customer/new_request.html", categories=CATEGORIES,
                                    providers=providers, form=request.form)

        req_id = execute(
            """INSERT INTO service_requests
               (customer_id, provider_id, category, item_name, brand, model, serial_number,
                problem_description, preferred_service, expected_completion_date, additional_notes,
                status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
            (g.user["id"], provider["id"], category, item_name, brand, model, serial_number,
             problem_description, preferred_service, expected_completion_date or None,
             additional_notes, now_iso()),
        )
        log_audit(None, g.user["id"], "SERVICE_REQUEST_CREATED", None, f"request #{req_id}")
        notify(provider["owner_user_id"], "New service request",
               f"{g.user['name']} requested service for {item_name}.")
        flash("Service request submitted.", "success")
        return redirect(url_for("customer.requests_list"))

    return render_template("customer/new_request.html", categories=CATEGORIES,
                            providers=providers, form={})


@bp.route("/services")
@role_required("customer")
def services_list():
    records = query_all(
        """SELECT sr.*, sp.business_name FROM service_records sr
           JOIN service_providers sp ON sp.id = sr.provider_id
           WHERE sr.customer_id = ? ORDER BY sr.created_at DESC""",
        (g.user["id"],),
    )
    return render_template("customer/services.html", records=records)


@bp.route("/notifications")
@role_required("customer")
def notifications():
    items = query_all(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
        (g.user["id"],),
    )
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (g.user["id"],))
    return render_template("customer/notifications.html", items=items)


@bp.route("/profile")
@role_required("customer")
def profile():
    total = query_one("SELECT COUNT(*) c FROM service_records WHERE customer_id=?", (g.user["id"],))["c"]
    active = query_one(
        "SELECT COUNT(*) c FROM service_records WHERE customer_id=? AND status NOT IN ('COMPLETED','CANCELLED')",
        (g.user["id"],),
    )["c"]
    completed = query_one(
        "SELECT COUNT(*) c FROM service_records WHERE customer_id=? AND status='COMPLETED'",
        (g.user["id"],),
    )["c"]
    return render_template("customer/profile.html", total=total, active=active, completed=completed)
