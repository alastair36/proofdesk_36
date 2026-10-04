import re
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, abort
from werkzeug.security import generate_password_hash, check_password_hash

from db import query_one, execute
from utils.helpers import now_iso, log_audit

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def password_meets_requirements(password):
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Za-z]", password):
        return False, "Password must contain at least one letter."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one number."
    return True, None


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        # Never trust a client-supplied role: always re-read it from the DB,
        # and drop the session immediately if the account was suspended.
        if user is not None and user["status"] == "active":
            g.user = user
        else:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Please log in to continue.", "error")
                return redirect(url_for("auth.login", next=request.path))
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "customer")

        errors = []
        if not name:
            errors.append("Name is required.")
        if not EMAIL_RE.match(email):
            errors.append("Please enter a valid email address.")
        if role not in ("customer", "provider"):
            # Admin accounts cannot be self-registered - server-enforced, ignore client input
            role = "customer"
        ok, msg = password_meets_requirements(password)
        if not ok:
            errors.append(msg)
        if query_one("SELECT id FROM users WHERE email = ?", (email,)):
            errors.append("An account with this email already exists.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("auth/register.html", form=request.form)

        password_hash = generate_password_hash(password)
        user_id = execute(
            """INSERT INTO users (name, email, phone, password_hash, role, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?)""",
            (name, email, phone, password_hash, role, now_iso()),
        )

        if role == "provider":
            execute(
                """INSERT INTO service_providers
                   (owner_user_id, business_name, category, description, verification_status, created_at)
                   VALUES (?, ?, ?, ?, 'PENDING', ?)""",
                (user_id, f"{name}'s Business", request.form.get("category", "Other"), "", now_iso()),
            )

        log_audit(None, user_id, "ACCOUNT_REGISTERED", None, role)
        flash("Account created. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form={})


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = query_one("SELECT * FROM users WHERE email = ?", (email,))

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Incorrect email or password.", "error")
            return render_template("auth/login.html", email=email)

        if user["status"] != "active":
            flash("This account has been suspended. Contact support.", "error")
            return render_template("auth/login.html", email=email)

        session.clear()
        session["user_id"] = user["id"]
        log_audit(None, user["id"], "LOGIN")

        next_url = request.args.get("next")
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for(f"{user['role']}.dashboard"))

    return render_template("auth/login.html", email="")


@bp.route("/logout")
def logout():
    if g.user:
        log_audit(None, g.user["id"], "LOGOUT")
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
