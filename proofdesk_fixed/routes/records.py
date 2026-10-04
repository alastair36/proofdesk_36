from flask import Blueprint, render_template, g, abort, request, redirect, url_for, flash, send_from_directory
from db import query_one, query_all, execute
from auth import login_required
from utils.helpers import now_iso, log_audit, notify, generate_code
from utils.verification import check_handover_requirements, check_return_requirements
from utils.state_machine import assert_transition, InvalidTransitionError
from utils.uploads import validate_and_save, UploadError
from utils.qr import generate_qr_png
import os

bp = Blueprint("records", __name__, url_prefix="/records")

ACCESSORY_OPTIONS = ["Charger", "Cable", "Adapter", "Bag", "Mouse", "Keyboard", "Remote", "Case", "Manual"]
CONDITION_ITEMS = [
    "Exterior condition", "Scratches", "Cracks", "Dents", "Missing parts",
    "Existing damage", "Functional condition", "Other observations",
]
SEVERITY_OPTIONS = ["GOOD", "MINOR_ISSUE", "DAMAGED", "NOT_TESTED"]
EVIDENCE_ANGLES = ["Front", "Back", "Left", "Right", "Close-up of damage", "Accessories", "Other"]

TIMELINE_STEPS = [
    ("HANDOVER_PENDING", "Request created"),
    ("HANDOVER_PENDING", "Item received"),
    ("HANDOVER_VERIFIED", "Handover verified"),
    ("SERVICE_IN_PROGRESS", "Service in progress"),
    ("SERVICE_COMPLETED", "Service completed"),
    ("PAYMENT_PENDING", "Payment"),
    ("READY_FOR_RETURN", "Return"),
    ("COMPLETED", "Completed"),
]

STATUS_ORDER = [
    "DRAFT", "HANDOVER_PENDING", "HANDOVER_VERIFIED", "SERVICE_IN_PROGRESS",
    "SERVICE_COMPLETED", "PAYMENT_PENDING", "READY_FOR_RETURN", "RETURN_PENDING",
    "RETURN_VERIFIED", "COMPLETED",
]


def get_record_or_404(record_number):
    record = query_one(
        """SELECT sr.*, sp.business_name, sp.owner_user_id AS provider_owner_id,
                  u.name AS customer_name, u.email AS customer_email
           FROM service_records sr
           JOIN service_providers sp ON sp.id = sr.provider_id
           JOIN users u ON u.id = sr.customer_id
           WHERE sr.record_number = ?""",
        (record_number,),
    )
    if record is None:
        abort(404)
    return record


def authorize_record_access(record):
    """
    Only the customer who owns the record, the provider who owns it, or an
    admin may view it. This is checked on every request - never inferred
    from the URL alone, so guessing/incrementing a record number cannot leak
    another user's private data.
    """
    user = g.user
    if user is None:
        abort(403)
    if user["role"] == "admin":
        return
    if user["role"] == "customer" and user["id"] == record["customer_id"]:
        return
    if user["role"] == "provider" and user["id"] == record["provider_owner_id"]:
        return
    abort(403)


def timeline_state(current_status):
    """Build done/current/upcoming flags for the visual timeline."""
    if current_status in ("DISPUTED", "CANCELLED"):
        cur_index = -1
    else:
        cur_index = STATUS_ORDER.index(current_status) if current_status in STATUS_ORDER else -1

    steps = []
    for status, label in TIMELINE_STEPS:
        idx = STATUS_ORDER.index(status)
        if idx < cur_index:
            state = "done"
        elif idx == cur_index:
            state = "current"
        else:
            state = "upcoming"
        steps.append((label, state))
    return steps


@bp.route("/<record_number>")
def view_record(record_number):
    record = get_record_or_404(record_number)
    authorize_record_access(record)

    accessories = query_all(
        "SELECT * FROM accessories WHERE service_record_id = ?", (record["id"],)
    )
    conditions_handover = query_all(
        "SELECT * FROM condition_reports WHERE service_record_id = ? AND stage='HANDOVER'", (record["id"],)
    )
    conditions_return = query_all(
        "SELECT * FROM condition_reports WHERE service_record_id = ? AND stage='RETURN'", (record["id"],)
    )
    evidence_handover = query_all(
        "SELECT * FROM evidence_files WHERE service_record_id = ? AND stage='HANDOVER'", (record["id"],)
    )
    evidence_return = query_all(
        "SELECT * FROM evidence_files WHERE service_record_id = ? AND stage='RETURN'", (record["id"],)
    )
    confirmations = query_all(
        "SELECT * FROM confirmations WHERE service_record_id = ?", (record["id"],)
    )
    service_updates = query_all(
        """SELECT su.*, u.name AS created_by_name FROM service_updates su
           JOIN users u ON u.id = su.created_by
           WHERE su.service_record_id = ? ORDER BY su.created_at""",
        (record["id"],),
    )
    cost_approvals = query_all(
        "SELECT * FROM cost_approvals WHERE service_record_id = ? ORDER BY created_at DESC", (record["id"],)
    )
    payments = query_all(
        "SELECT * FROM payments WHERE service_record_id = ? ORDER BY created_at DESC", (record["id"],)
    )
    return_row = query_one("SELECT * FROM returns WHERE service_record_id = ?", (record["id"],))
    disputes = query_all(
        "SELECT * FROM disputes WHERE service_record_id = ? ORDER BY created_at DESC", (record["id"],)
    )
    audit_logs = query_all(
        """SELECT al.*, u.name AS user_name FROM audit_logs al
           LEFT JOIN users u ON u.id = al.user_id
           WHERE al.service_record_id = ? ORDER BY al.created_at""",
        (record["id"],),
    )

    cust_confirmed = any(c["role"] == "customer" and c["confirmation_type"] == "HANDOVER" for c in confirmations)
    prov_confirmed = any(c["role"] == "provider" and c["confirmation_type"] == "HANDOVER" for c in confirmations)

    return render_template(
        "records/view.html",
        record=record,
        accessories=accessories,
        conditions_handover=conditions_handover,
        conditions_return=conditions_return,
        evidence_handover=evidence_handover,
        evidence_return=evidence_return,
        confirmations=confirmations,
        cust_confirmed=cust_confirmed,
        prov_confirmed=prov_confirmed,
        service_updates=service_updates,
        cost_approvals=cost_approvals,
        payments=payments,
        return_row=return_row,
        disputes=disputes,
        audit_logs=audit_logs,
        timeline=timeline_state(record["status"]),
        is_customer=(g.user["role"] == "customer"),
        is_provider=(g.user["role"] == "provider"),
        is_admin=(g.user["role"] == "admin"),
    )


def require_editable_handover(record):
    """Handover documentation may only be edited while HANDOVER_PENDING and
    only before that party's own confirmation - never on a verified/locked record."""
    if record["status"] != "HANDOVER_PENDING":
        abort(403, description="Handover stage is closed for this record.")


def require_provider_owner(record):
    if g.user["role"] != "provider" or g.user["id"] != record["provider_owner_id"]:
        abort(403)


@bp.route("/<record_number>/handover")
@login_required
def handover_page(record_number):
    record = get_record_or_404(record_number)
    authorize_record_access(record)
    accessories = query_all("SELECT * FROM accessories WHERE service_record_id = ?", (record["id"],))
    conditions = query_all(
        "SELECT * FROM condition_reports WHERE service_record_id = ? AND stage='HANDOVER'", (record["id"],)
    )
    evidence = query_all(
        "SELECT * FROM evidence_files WHERE service_record_id = ? AND stage='HANDOVER'", (record["id"],)
    )
    is_verified, satisfied, missing = check_handover_requirements(record["id"])
    confirmations = query_all(
        "SELECT * FROM confirmations WHERE service_record_id = ? AND confirmation_type='HANDOVER'", (record["id"],)
    )
    cust_confirmed = any(c["role"] == "customer" for c in confirmations)
    prov_confirmed = any(c["role"] == "provider" for c in confirmations)
    existing_accessory_names = {a["name"] for a in accessories}

    return render_template(
        "records/handover.html",
        record=record, accessories=accessories, conditions=conditions, evidence=evidence,
        is_verified=is_verified, satisfied=satisfied, missing=missing,
        cust_confirmed=cust_confirmed, prov_confirmed=prov_confirmed,
        accessory_options=ACCESSORY_OPTIONS, condition_items=CONDITION_ITEMS,
        severity_options=SEVERITY_OPTIONS, evidence_angles=EVIDENCE_ANGLES,
        existing_accessory_names=existing_accessory_names,
        editable=(record["status"] == "HANDOVER_PENDING"),
        is_customer=(g.user["role"] == "customer"),
        is_provider=(g.user["role"] == "provider" and g.user["id"] == record["provider_owner_id"]),
        is_admin=(g.user["role"] == "admin"),
    )


@bp.route("/<record_number>/accessories", methods=["POST"])
@login_required
def save_accessories(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_editable_handover(record)

    old_count = query_one(
        "SELECT COUNT(*) c FROM accessories WHERE service_record_id=?", (record["id"],)
    )["c"]

    execute("DELETE FROM accessories WHERE service_record_id = ?", (record["id"],))
    for name in ACCESSORY_OPTIONS:
        received = 1 if request.form.get(f"acc_{name}") == "yes" else 0
        execute(
            "INSERT INTO accessories (service_record_id, name, received) VALUES (?, ?, ?)",
            (record["id"], name, received),
        )
    custom_names = request.form.get("custom_accessories", "").strip()
    if custom_names:
        for name in [n.strip() for n in custom_names.split(",") if n.strip()]:
            execute(
                "INSERT INTO accessories (service_record_id, name, received) VALUES (?, ?, 1)",
                (record["id"], name),
            )

    log_audit(record["id"], g.user["id"], "ACCESSORIES_RECORDED",
              str(old_count), "checklist updated")
    flash("Accessories checklist saved.", "success")
    return redirect(url_for("records.handover_page", record_number=record_number))


@bp.route("/<record_number>/condition", methods=["POST"])
@login_required
def save_condition(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_editable_handover(record)

    execute(
        "DELETE FROM condition_reports WHERE service_record_id = ? AND stage='HANDOVER'", (record["id"],)
    )
    ts = now_iso()
    saved_any = False
    for item in CONDITION_ITEMS:
        key = item.replace(" ", "_")
        severity = request.form.get(f"severity_{key}", "")
        notes = request.form.get(f"notes_{key}", "").strip()
        if severity not in SEVERITY_OPTIONS:
            continue
        execute(
            """INSERT INTO condition_reports
               (service_record_id, stage, condition_type, severity, description, created_at)
               VALUES (?, 'HANDOVER', ?, ?, ?, ?)""",
            (record["id"], item, severity, notes, ts),
        )
        saved_any = True

    if not saved_any:
        flash("Select a condition rating for at least one item.", "error")
        return redirect(url_for("records.handover_page", record_number=record_number))

    log_audit(record["id"], g.user["id"], "CONDITION_UPDATED", None, "handover condition recorded")
    flash("Condition checklist saved.", "success")
    return redirect(url_for("records.handover_page", record_number=record_number))


@bp.route("/<record_number>/evidence", methods=["POST"])
@login_required
def upload_evidence(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_editable_handover(record)

    angle = request.form.get("angle", "Other")
    file_storage = request.files.get("photo")
    try:
        rel_path, real_format = validate_and_save(file_storage, subdir=f"record_{record['id']}")
    except UploadError as e:
        flash(str(e), "error")
        return redirect(url_for("records.handover_page", record_number=record_number))

    execute(
        """INSERT INTO evidence_files
           (service_record_id, uploaded_by, stage, angle, file_reference, file_type, created_at)
           VALUES (?, ?, 'HANDOVER', ?, ?, ?, ?)""",
        (record["id"], g.user["id"], angle, rel_path, real_format, now_iso()),
    )
    log_audit(record["id"], g.user["id"], "PHOTOGRAPH_UPLOADED", None, f"{angle} photo")
    flash("Photograph uploaded.", "success")
    return redirect(url_for("records.handover_page", record_number=record_number))


@bp.route("/<record_number>/confirm-handover", methods=["POST"])
@login_required
def confirm_handover(record_number):
    record = get_record_or_404(record_number)
    authorize_record_access(record)

    if record["status"] != "HANDOVER_PENDING":
        flash("This record is not awaiting handover confirmation.", "error")
        return redirect(url_for("records.handover_page", record_number=record_number))

    role = g.user["role"]
    if role not in ("customer", "provider"):
        abort(403)
    if role == "customer" and g.user["id"] != record["customer_id"]:
        abort(403)
    if role == "provider" and g.user["id"] != record["provider_owner_id"]:
        abort(403)

    # Prevent duplicate confirmation - a user can only confirm their own role, once.
    existing = query_one(
        "SELECT id FROM confirmations WHERE service_record_id=? AND role=? AND confirmation_type='HANDOVER'",
        (record["id"], role),
    )
    if existing:
        flash("You have already confirmed this handover.", "error")
        return redirect(url_for("records.handover_page", record_number=record_number))

    execute(
        """INSERT INTO confirmations (service_record_id, user_id, role, confirmation_type, confirmed_at)
           VALUES (?, ?, ?, 'HANDOVER', ?)""",
        (record["id"], g.user["id"], role, now_iso()),
    )
    log_audit(record["id"], g.user["id"], f"{role.upper()}_CONFIRMED_HANDOVER")

    is_verified, satisfied, missing = check_handover_requirements(record["id"])
    if is_verified:
        assert_transition("HANDOVER_PENDING", "HANDOVER_VERIFIED")
        verification_code = generate_code(10)
        execute(
            "UPDATE service_records SET status='HANDOVER_VERIFIED', verification_code=? WHERE id=?",
            (verification_code, record["id"]),
        )
        log_audit(record["id"], g.user["id"], "STATUS_CHANGED", "HANDOVER_PENDING", "HANDOVER_VERIFIED")

        verify_url = request.host_url.rstrip("/") + url_for("records.public_verify", code=verification_code)
        from utils.paths import QR_DIR
        generate_qr_png(verify_url, os.path.join(QR_DIR, f"{verification_code}.png"))

        notify(record["customer_id"], "Handover verified",
               f"Handover for {record['record_number']} is verified. Service can now begin.", record["id"])
        notify(record["provider_owner_id"], "Handover verified",
               f"Handover for {record['record_number']} is verified. Service can now begin.", record["id"])
        flash("Handover fully verified! Verification code and QR generated.", "success")
    else:
        flash(f"Confirmation recorded. Verification incomplete — missing: {', '.join(missing)}.", "info")

    return redirect(url_for("records.handover_page", record_number=record_number))


@bp.route("/verify/<code>")
def public_verify(code):
    """Public, unauthenticated QR-scan landing page. Reveals only a safe,
    non-sensitive summary of the record - never customer personal data."""
    record = query_one(
        "SELECT record_number, status, created_at, verification_code FROM service_records WHERE verification_code = ?",
        (code,),
    )
    if record is None:
        abort(404)
    return render_template("records/public_verify.html", record=record)


# ---------------------------------------------------------------------------
# PHASE 4: Service workflow, additional-cost approval, payments, returns
# ---------------------------------------------------------------------------

SERVICE_UPDATE_TYPES = ["DIAGNOSIS", "SERVICE_PERFORMED", "PARTS_USED", "TECHNICIAN_NOTE", "ADDITIONAL_ISSUE"]
PAYMENT_METHODS = ["Cash", "UPI", "Card", "Bank Transfer", "Other"]


def require_not_locked(record):
    if record["locked_at"]:
        abort(403, description="Record is locked and cannot be edited.")


@bp.route("/<record_number>/start-service", methods=["POST"])
@login_required
def start_service(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    try:
        assert_transition(record["status"], "SERVICE_IN_PROGRESS")
    except InvalidTransitionError as e:
        flash(str(e), "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    execute("UPDATE service_records SET status='SERVICE_IN_PROGRESS' WHERE id=?", (record["id"],))
    log_audit(record["id"], g.user["id"], "SERVICE_STARTED", record["status"], "SERVICE_IN_PROGRESS")
    notify(record["customer_id"], "Service started",
           f"Work has started on your {record['item_name']} ({record_number}).", record["id"])
    flash("Service started.", "success")
    return redirect(url_for("records.view_record", record_number=record_number))


@bp.route("/<record_number>/service-update", methods=["POST"])
@login_required
def add_service_update(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)
    if record["status"] != "SERVICE_IN_PROGRESS":
        flash("Service updates can only be added while service is in progress.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    update_type = request.form.get("update_type", "")
    description = request.form.get("description", "").strip()
    if update_type not in SERVICE_UPDATE_TYPES or not description:
        flash("Please select an update type and enter a description.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    execute(
        """INSERT INTO service_updates (service_record_id, update_type, description, created_by, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (record["id"], update_type, description, g.user["id"], now_iso()),
    )
    log_audit(record["id"], g.user["id"], f"{update_type}_ADDED", None, description[:120])
    flash("Service update added.", "success")
    return redirect(url_for("records.view_record", record_number=record_number))


@bp.route("/<record_number>/update-cost", methods=["POST"])
@login_required
def update_cost(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)
    if record["status"] != "SERVICE_IN_PROGRESS":
        flash("Cost can only be updated while service is in progress.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    try:
        new_cost = float(request.form.get("new_cost", ""))
    except ValueError:
        flash("Please enter a valid cost.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))
    if new_cost < 0:
        flash("Cost cannot be negative.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    if new_cost > record["estimated_cost"]:
        additional = round(new_cost - record["estimated_cost"], 2)
        execute(
            """INSERT INTO cost_approvals (service_record_id, original_cost, additional_cost, total_cost,
               status, created_at) VALUES (?, ?, ?, ?, 'PENDING', ?)""",
            (record["id"], record["estimated_cost"], additional, new_cost, now_iso()),
        )
        log_audit(record["id"], g.user["id"], "ADDITIONAL_COST_REQUESTED",
                  str(record["estimated_cost"]), str(new_cost))
        notify(record["customer_id"], "Additional cost approval required",
               f"Additional cost of ₹{additional:.2f} requires your approval for {record_number} "
               f"(new total ₹{new_cost:.2f}).", record["id"])
        flash("Cost exceeds the original estimate - customer approval has been requested.", "info")
    else:
        execute("UPDATE service_records SET final_cost = ? WHERE id = ?", (new_cost, record["id"]))
        log_audit(record["id"], g.user["id"], "COST_CHANGED", str(record["estimated_cost"]), str(new_cost))
        flash("Final cost updated.", "success")

    return redirect(url_for("records.view_record", record_number=record_number))


@bp.route("/<record_number>/cost-approval/<int:approval_id>/decide", methods=["POST"])
@login_required
def decide_cost_approval(record_number, approval_id):
    record = get_record_or_404(record_number)
    if g.user["role"] != "customer" or g.user["id"] != record["customer_id"]:
        abort(403)
    approval = query_one(
        "SELECT * FROM cost_approvals WHERE id = ? AND service_record_id = ?", (approval_id, record["id"])
    )
    if approval is None:
        abort(404)
    if approval["status"] != "PENDING":
        flash("This cost approval has already been decided.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    decision = request.form.get("decision")
    if decision not in ("APPROVE", "DECLINE"):
        abort(400)

    ts = now_iso()
    new_status = "APPROVED" if decision == "APPROVE" else "DECLINED"
    execute(
        "UPDATE cost_approvals SET status=?, approved_by=?, approved_at=? WHERE id=?",
        (new_status, g.user["id"], ts, approval_id),
    )
    if decision == "APPROVE":
        execute("UPDATE service_records SET final_cost = ? WHERE id = ?", (approval["total_cost"], record["id"]))
    log_audit(record["id"], g.user["id"], f"ADDITIONAL_COST_{new_status}",
              "PENDING", new_status)
    notify(record["provider_owner_id"],
           f"Additional cost {new_status.lower()}",
           f"The customer {new_status.lower()} the additional ₹{approval['additional_cost']:.2f} "
           f"charge on {record_number}.", record["id"])
    flash(f"Additional cost {new_status.lower()}.", "success")
    return redirect(url_for("records.view_record", record_number=record_number))


@bp.route("/<record_number>/complete-service", methods=["POST"])
@login_required
def complete_service(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)

    pending = query_one(
        "SELECT id FROM cost_approvals WHERE service_record_id = ? AND status = 'PENDING'", (record["id"],)
    )
    if pending:
        flash("Cannot complete service while an additional cost approval is pending.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    try:
        assert_transition(record["status"], "SERVICE_COMPLETED")
    except InvalidTransitionError as e:
        flash(str(e), "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    final_cost = record["final_cost"] if record["final_cost"] is not None else record["estimated_cost"]
    execute(
        "UPDATE service_records SET status='SERVICE_COMPLETED', final_cost=? WHERE id=?",
        (final_cost, record["id"]),
    )
    log_audit(record["id"], g.user["id"], "STATUS_CHANGED", "SERVICE_IN_PROGRESS", "SERVICE_COMPLETED")

    assert_transition("SERVICE_COMPLETED", "PAYMENT_PENDING")
    execute("UPDATE service_records SET status='PAYMENT_PENDING' WHERE id=?", (record["id"],))
    log_audit(record["id"], g.user["id"], "STATUS_CHANGED", "SERVICE_COMPLETED", "PAYMENT_PENDING")

    notify(record["customer_id"], "Service completed",
           f"Service on {record['item_name']} ({record_number}) is complete. "
           f"Amount due: ₹{final_cost:.2f}.", record["id"])
    flash("Service marked complete. Awaiting payment.", "success")
    return redirect(url_for("records.view_record", record_number=record_number))


@bp.route("/<record_number>/record-payment", methods=["POST"])
@login_required
def record_payment(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)
    if record["status"] != "PAYMENT_PENDING":
        flash("Payment can only be recorded while payment is pending.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    try:
        amount = float(request.form.get("amount", ""))
    except ValueError:
        flash("Please enter a valid amount.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))
    if amount < 0:
        flash("Amount cannot be negative.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))
    method = request.form.get("method", "")
    reference = request.form.get("reference", "").strip()
    if method not in PAYMENT_METHODS:
        flash("Please select a valid payment method.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    execute(
        """INSERT INTO payments (service_record_id, amount, method, reference, status, recorded_by, created_at)
           VALUES (?, ?, ?, ?, 'PAID', ?, ?)""",
        (record["id"], amount, method, reference or None, g.user["id"], now_iso()),
    )
    log_audit(record["id"], g.user["id"], "PAYMENT_RECORDED", None, f"₹{amount:.2f} via {method}")

    total_paid = query_one(
        "SELECT COALESCE(SUM(amount),0) t FROM payments WHERE service_record_id=? AND status='PAID'",
        (record["id"],),
    )["t"]
    flash(
        f"Payment of ₹{amount:.2f} recorded (this is a payment record, not a live payment gateway charge).",
        "success",
    )
    if total_paid >= (record["final_cost"] or 0):
        flash("Full amount recorded as paid. You can now mark the item ready for return.", "info")
    return redirect(url_for("records.view_record", record_number=record_number))


@bp.route("/<record_number>/ready-for-return", methods=["POST"])
@login_required
def ready_for_return(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)

    total_paid = query_one(
        "SELECT COALESCE(SUM(amount),0) t FROM payments WHERE service_record_id=? AND status='PAID'",
        (record["id"],),
    )["t"]
    if total_paid < (record["final_cost"] or 0):
        flash("Full payment must be recorded before marking the item ready for return.", "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    try:
        assert_transition(record["status"], "READY_FOR_RETURN")
    except InvalidTransitionError as e:
        flash(str(e), "error")
        return redirect(url_for("records.view_record", record_number=record_number))

    execute("UPDATE service_records SET status='READY_FOR_RETURN' WHERE id=?", (record["id"],))
    log_audit(record["id"], g.user["id"], "STATUS_CHANGED", "PAYMENT_PENDING", "READY_FOR_RETURN")
    notify(record["customer_id"], "Your item is ready for pickup.",
           f"{record['item_name']} ({record_number}) is ready to be returned.", record["id"])
    flash("Marked ready for return.", "success")
    return redirect(url_for("records.view_record", record_number=record_number))


@bp.route("/<record_number>/return")
@login_required
def return_page(record_number):
    record = get_record_or_404(record_number)
    authorize_record_access(record)
    accessories = query_all("SELECT * FROM accessories WHERE service_record_id = ?", (record["id"],))
    conditions = query_all(
        "SELECT * FROM condition_reports WHERE service_record_id = ? AND stage='RETURN'", (record["id"],)
    )
    evidence = query_all(
        "SELECT * FROM evidence_files WHERE service_record_id = ? AND stage='RETURN'", (record["id"],)
    )
    return_row = query_one("SELECT * FROM returns WHERE service_record_id = ?", (record["id"],))
    is_verified, satisfied, missing = check_return_requirements(record["id"])
    return render_template(
        "records/return.html",
        record=record, accessories=accessories, conditions=conditions, evidence=evidence,
        return_row=return_row, is_verified=is_verified, satisfied=satisfied, missing=missing,
        condition_items=CONDITION_ITEMS, severity_options=SEVERITY_OPTIONS, evidence_angles=EVIDENCE_ANGLES,
        is_customer=(g.user["role"] == "customer"),
        is_provider=(g.user["role"] == "provider" and g.user["id"] == record["provider_owner_id"]),
        is_admin=(g.user["role"] == "admin"),
    )


@bp.route("/<record_number>/generate-return-code", methods=["POST"])
@login_required
def generate_return_code(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)
    try:
        assert_transition(record["status"], "RETURN_PENDING")
    except InvalidTransitionError as e:
        flash(str(e), "error")
        return redirect(url_for("records.return_page", record_number=record_number))

    code = generate_code(6)
    existing = query_one("SELECT id FROM returns WHERE service_record_id=?", (record["id"],))
    if existing:
        execute("UPDATE returns SET return_code=? WHERE service_record_id=?", (code, record["id"]))
    else:
        execute(
            "INSERT INTO returns (service_record_id, return_code) VALUES (?, ?)",
            (record["id"], code),
        )
    execute("UPDATE service_records SET status='RETURN_PENDING', return_code=? WHERE id=?", (code, record["id"]))
    log_audit(record["id"], g.user["id"], "RETURN_INITIATED", "READY_FOR_RETURN", "RETURN_PENDING")
    notify(record["customer_id"], "Return confirmation required",
           f"Your return code for {record_number} is {code}. Provide this code when collecting your item.",
           record["id"])
    flash(f"Return code generated: {code}", "success")
    return redirect(url_for("records.return_page", record_number=record_number))


@bp.route("/<record_number>/confirm-return-code", methods=["POST"])
@login_required
def confirm_return_code(record_number):
    record = get_record_or_404(record_number)
    if g.user["role"] != "customer" or g.user["id"] != record["customer_id"]:
        abort(403)
    if record["locked_at"]:
        abort(403, description="Record is locked and cannot be edited.")
    if record["status"] != "RETURN_PENDING":
        flash("Return confirmation is not required at this time.", "error")
        return redirect(url_for("records.return_page", record_number=record_number))

    entered = request.form.get("code", "").strip().upper()
    ret = query_one("SELECT * FROM returns WHERE service_record_id=?", (record["id"],))
    if not ret or entered != ret["return_code"]:
        flash("Incorrect return code.", "error")
        return redirect(url_for("records.return_page", record_number=record_number))
    if ret["returned_at"]:
        flash("Return has already been confirmed.", "error")
        return redirect(url_for("records.return_page", record_number=record_number))

    execute(
        "UPDATE returns SET returned_by=?, returned_at=? WHERE service_record_id=?",
        (g.user["id"], now_iso(), record["id"]),
    )
    log_audit(record["id"], g.user["id"], "RETURN_CODE_CONFIRMED")
    flash("Return code confirmed. Awaiting provider verification.", "success")
    return redirect(url_for("records.return_page", record_number=record_number))


@bp.route("/<record_number>/return-condition", methods=["POST"])
@login_required
def save_return_condition(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)
    execute("DELETE FROM condition_reports WHERE service_record_id=? AND stage='RETURN'", (record["id"],))
    ts = now_iso()
    for item in CONDITION_ITEMS:
        key = item.replace(" ", "_")
        severity = request.form.get(f"severity_{key}", "")
        notes = request.form.get(f"notes_{key}", "").strip()
        if severity not in SEVERITY_OPTIONS:
            continue
        execute(
            """INSERT INTO condition_reports (service_record_id, stage, condition_type, severity, description, created_at)
               VALUES (?, 'RETURN', ?, ?, ?, ?)""",
            (record["id"], item, severity, notes, ts),
        )
    log_audit(record["id"], g.user["id"], "RETURN_CONDITION_RECORDED")
    flash("Return condition recorded.", "success")
    return redirect(url_for("records.return_page", record_number=record_number))


@bp.route("/<record_number>/return-accessories", methods=["POST"])
@login_required
def save_return_accessories(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)
    accessories = query_all("SELECT * FROM accessories WHERE service_record_id=?", (record["id"],))
    for a in accessories:
        returned = 1 if request.form.get(f"ret_{a['id']}") == "yes" else 0
        execute("UPDATE accessories SET returned=? WHERE id=?", (returned, a["id"]))
    log_audit(record["id"], g.user["id"], "RETURN_ACCESSORIES_RECORDED")
    flash("Returned accessories recorded.", "success")
    return redirect(url_for("records.return_page", record_number=record_number))


@bp.route("/<record_number>/return-evidence", methods=["POST"])
@login_required
def upload_return_evidence(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)
    angle = request.form.get("angle", "Other")
    file_storage = request.files.get("photo")
    try:
        rel_path, real_format = validate_and_save(file_storage, subdir=f"record_{record['id']}")
    except UploadError as e:
        flash(str(e), "error")
        return redirect(url_for("records.return_page", record_number=record_number))
    execute(
        """INSERT INTO evidence_files (service_record_id, uploaded_by, stage, angle, file_reference, file_type, created_at)
           VALUES (?, ?, 'RETURN', ?, ?, ?, ?)""",
        (record["id"], g.user["id"], angle, rel_path, real_format, now_iso()),
    )
    log_audit(record["id"], g.user["id"], "RETURN_PHOTOGRAPH_UPLOADED")
    flash("Return photograph uploaded.", "success")
    return redirect(url_for("records.return_page", record_number=record_number))


@bp.route("/<record_number>/verify-return", methods=["POST"])
@login_required
def verify_return(record_number):
    record = get_record_or_404(record_number)
    require_provider_owner(record)
    require_not_locked(record)

    ret = query_one("SELECT * FROM returns WHERE service_record_id=?", (record["id"],))
    if not ret or not ret["returned_at"]:
        flash("Customer must confirm the return code before it can be verified.", "error")
        return redirect(url_for("records.return_page", record_number=record_number))

    condition_summary = request.form.get("condition_summary", "").strip()
    execute(
        "UPDATE returns SET received_by=?, condition_summary=?, verified_at=? WHERE service_record_id=?",
        (g.user["id"], condition_summary, now_iso(), record["id"]),
    )

    is_verified, satisfied, missing = check_return_requirements(record["id"])
    if not is_verified:
        flash(f"Return verification incomplete — missing: {', '.join(missing)}.", "error")
        return redirect(url_for("records.return_page", record_number=record_number))

    try:
        assert_transition(record["status"], "RETURN_VERIFIED")
    except InvalidTransitionError as e:
        flash(str(e), "error")
        return redirect(url_for("records.return_page", record_number=record_number))

    execute("UPDATE service_records SET status='RETURN_VERIFIED' WHERE id=?", (record["id"],))
    log_audit(record["id"], g.user["id"], "STATUS_CHANGED", "RETURN_PENDING", "RETURN_VERIFIED")

    # Return verification is the final gate - the record is now complete and locked.
    assert_transition("RETURN_VERIFIED", "COMPLETED")
    ts = now_iso()
    execute("UPDATE service_records SET status='COMPLETED', locked_at=? WHERE id=?", (ts, record["id"]))
    log_audit(record["id"], g.user["id"], "STATUS_CHANGED", "RETURN_VERIFIED", "COMPLETED")
    log_audit(record["id"], g.user["id"], "RECORD_COMPLETED", None,
              "Original handover, condition, accessories, photographs and confirmations are now locked.")
    notify(record["customer_id"], "Your service record has been completed.",
           f"{record['item_name']} ({record_number}) is complete and the record is now locked.", record["id"])
    notify(record["provider_owner_id"], "Service record completed.",
           f"{record_number} is complete and locked.", record["id"])
    flash("Return verified. Service record is now COMPLETED and locked.", "success")
    return redirect(url_for("records.return_page", record_number=record_number))


# ---------------------------------------------------------------------------
# PHASE 5: Before/after comparison, disputes, audit trail is already logged
# throughout; record locking is enforced by require_not_locked() below.
# ---------------------------------------------------------------------------

DISPUTE_CATEGORIES = [
    "MISSING_ACCESSORY", "CONDITION_DISAGREEMENT", "ITEM_NOT_RETURNED",
    "INCORRECT_SERVICE", "INCORRECT_CHARGE", "OTHER",
]


@bp.route("/<record_number>/compare")
@login_required
def compare_page(record_number):
    record = get_record_or_404(record_number)
    authorize_record_access(record)
    accessories = query_all("SELECT * FROM accessories WHERE service_record_id=?", (record["id"],))
    cond_h = query_all(
        "SELECT * FROM condition_reports WHERE service_record_id=? AND stage='HANDOVER'", (record["id"],)
    )
    cond_r = query_all(
        "SELECT * FROM condition_reports WHERE service_record_id=? AND stage='RETURN'", (record["id"],)
    )
    ev_h = query_all(
        "SELECT * FROM evidence_files WHERE service_record_id=? AND stage='HANDOVER'", (record["id"],)
    )
    ev_r = query_all(
        "SELECT * FROM evidence_files WHERE service_record_id=? AND stage='RETURN'", (record["id"],)
    )
    return render_template(
        "records/compare.html", record=record, accessories=accessories,
        cond_h=cond_h, cond_r=cond_r, ev_h=ev_h, ev_r=ev_r,
    )


@bp.route("/<record_number>/dispute/new", methods=["GET", "POST"])
@login_required
def open_dispute(record_number):
    record = get_record_or_404(record_number)
    authorize_record_access(record)
    if g.user["role"] != "customer" or g.user["id"] != record["customer_id"]:
        abort(403)

    if request.method == "POST":
        category = request.form.get("category", "")
        description = request.form.get("description", "").strip()
        if category not in DISPUTE_CATEGORIES:
            flash("Please select a valid dispute category.", "error")
            return redirect(url_for("records.open_dispute", record_number=record_number))
        if not description:
            flash("Please describe the issue.", "error")
            return redirect(url_for("records.open_dispute", record_number=record_number))

        existing_open = query_one(
            "SELECT id FROM disputes WHERE service_record_id=? AND status != 'CLOSED'", (record["id"],)
        )
        if existing_open:
            flash("There is already an open dispute on this record.", "error")
            return redirect(url_for("records.view_record", record_number=record_number))

        dispute_id = execute(
            """INSERT INTO disputes (service_record_id, opened_by, category, description,
               status, previous_status, created_at) VALUES (?, ?, ?, ?, 'OPEN', ?, ?)""",
            (record["id"], g.user["id"], category, description, record["status"], now_iso()),
        )

        evidence_file = request.files.get("evidence")
        if evidence_file and evidence_file.filename:
            try:
                rel_path, real_format = validate_and_save(evidence_file, subdir=f"record_{record['id']}")
                execute(
                    """INSERT INTO evidence_files (service_record_id, uploaded_by, stage, angle,
                       file_reference, file_type, created_at) VALUES (?, ?, 'DISPUTE', 'dispute evidence', ?, ?, ?)""",
                    (record["id"], g.user["id"], rel_path, real_format, now_iso()),
                )
            except UploadError as e:
                flash(f"Dispute opened, but evidence upload failed: {e}", "info")

        assert_transition(record["status"], "DISPUTED")
        execute("UPDATE service_records SET status='DISPUTED' WHERE id=?", (record["id"],))
        log_audit(record["id"], g.user["id"], "DISPUTE_OPENED", record["status"], category)
        notify(record["provider_owner_id"], "A dispute has been opened.",
               f"A dispute was opened on {record_number}: {category.replace('_',' ')}.", record["id"])
        flash("Dispute opened. An administrator will review the evidence.", "success")
        return redirect(url_for("records.view_record", record_number=record_number))

    return render_template("records/new_dispute.html", record=record, categories=DISPUTE_CATEGORIES)
