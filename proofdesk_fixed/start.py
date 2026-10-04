"""
One-command launcher for ProofDesk (Windows / macOS / Linux).

    python start.py            -> install deps (first time), load demo data, open browser
    python start.py phone      -> same, but reachable from a phone on the same Wi-Fi
"""
import os
import sqlite3
import socket
import subprocess
import sys
import threading
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)
PORT = int(os.environ.get("PORT", "5050"))


def deps_ok():
    try:
        import flask, PIL, dotenv, qrcode  # noqa: F401
        return True
    except ImportError:
        return False


def install_deps():
    if os.environ.get("PROOFDESK_SKIP_INSTALL") == "1" or deps_ok():
        return
    print("Installing dependencies (first run only, needs internet)...")
    r = subprocess.call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    if r != 0 or not deps_ok():
        print("\nCould not install dependencies. Check your internet connection and try again.")
        sys.exit(1)


def needs_seed():
    db = os.path.join(BASE, "instance", "proofdesk.db")
    if not os.path.exists(db):
        return True
    try:
        con = sqlite3.connect(db)
        n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        con.close()
        return n == 0
    except sqlite3.Error:
        return True


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "YOUR-PC-IP"


def port_free(host):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) != 0


def main():
    phone = len(sys.argv) > 1 and sys.argv[1].lower() == "phone"
    install_deps()

    if not os.path.exists(".env") and os.path.exists(".env.example"):
        import shutil
        shutil.copy(".env.example", ".env")

    if needs_seed():
        print("Loading demo data...")
        if subprocess.call([sys.executable, "seed_demo.py"], stdout=subprocess.DEVNULL) != 0:
            print("Seeding failed. Run: python seed_demo.py  to see the error.")
            sys.exit(1)

    if not port_free("127.0.0.1"):
        print(f"Port {PORT} is already in use (is ProofDesk already running?). "
              f"Open http://127.0.0.1:{PORT} or close the other window.")
        sys.exit(1)

    host = "0.0.0.0" if phone else "127.0.0.1"
    os.environ["HOST"] = host
    url = f"http://127.0.0.1:{PORT}"

    print("\n==============================================")
    print(f"  ProofDesk running at {url}")
    if phone:
        print(f"  On your phone (same Wi-Fi): http://{lan_ip()}:{PORT}")
    print("  Demo logins (password Demo@1234):")
    print("    customer@proofdesk.demo")
    print("    provider@proofdesk.demo")
    print("    admin@proofdesk.demo")
    print("  Press Ctrl+C to stop.")
    print("==============================================\n")

    if os.environ.get("PROOFDESK_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    from app import app
    app.run(host=host, port=PORT, debug=False)


if __name__ == "__main__":
    main()
