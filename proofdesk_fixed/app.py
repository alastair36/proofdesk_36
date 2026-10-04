import os
import secrets
from dotenv import load_dotenv
from flask import Flask, render_template, g, redirect, url_for, send_from_directory, abort

load_dotenv()  # reads .env if present

from db import init_db
from utils.paths import IS_SERVERLESS, UPLOAD_DIR, QR_DIR, MAX_UPLOAD_BYTES
from auth import bp as auth_bp, login_required


def create_app():
    app = Flask(__name__)

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        if IS_SERVERLESS:
            # Serverless runs many short-lived instances; a random key per instance would log
            # people out whenever a new instance spins up. Set SECRET_KEY in Vercel to override.
            secret = "proofdesk-demo-deployment-key-set-SECRET_KEY-env-var-for-real-use"
        else:
            # Dev fallback only. In production SECRET_KEY must be set via env var.
            secret = secrets.token_hex(32)
    app.config["SECRET_KEY"] = secret
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 1024 * 1024  # hard cap slightly above per-file check
    if IS_SERVERLESS:
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    init_db(app)

    if IS_SERVERLESS:
        _bootstrap_demo_data(app)

    app.register_blueprint(auth_bp)

    from routes.customer import bp as customer_bp
    from routes.provider import bp as provider_bp
    from routes.admin import bp as admin_bp
    from routes.records import bp as records_bp

    app.register_blueprint(customer_bp)
    app.register_blueprint(provider_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(records_bp)

    @app.context_processor
    def inject_globals():
        return {"max_mb": MAX_UPLOAD_BYTES // (1024 * 1024)}

    # Uploaded photos + QR codes live outside /static on Vercel (read-only project dir).
    # These more-specific routes win over Flask's built-in /static handler and work locally too.
    @app.route("/static/uploads/<path:filename>")
    def serve_upload(filename):
        return send_from_directory(UPLOAD_DIR, filename)

    @app.route("/static/qr/<path:filename>")
    def serve_qr(filename):
        return send_from_directory(QR_DIR, filename)

    @app.context_processor
    def inject_unread_notifications():
        if g.get("user"):
            from db import query_one
            row = query_one(
                "SELECT COUNT(*) c FROM notifications WHERE user_id=? AND is_read=0", (g.user["id"],)
            )
            return {"unread_notifications": row["c"]}
        return {"unread_notifications": 0}

    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))
        return redirect(url_for(f"{g.user['role']}.dashboard"))

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors.html", code=403,
                                message="You are not authorized to perform this action."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors.html", code=404, message="Page not found."), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("errors.html", code=413, message="Uploaded file is too large."), 413

    return app


def _bootstrap_demo_data(app):
    """On a cold serverless start the temp DB is empty: load the demo dataset so the
    app is immediately usable (demo logins work, dashboards are populated)."""
    from db import query_one
    with app.app_context():
        if query_one("SELECT COUNT(*) c FROM users")["c"] == 0:
            from seed_demo import run_seed
            run_seed(app, quiet=True)


app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")   # set HOST=0.0.0.0 to open to your LAN/phone
    port = int(os.environ.get("PORT", "5050"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
