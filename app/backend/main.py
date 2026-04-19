"""LocalShop Finder backend entrypoint.

Flask application exposing the REST API consumed by the Flutter client in
`lib/features/**/data/datasources`. All endpoints are defined under feature
blueprints in the `routes/` package and persist data in Firestore under
`localshop/v1/<collection>`.
"""

import logging
import os

import firebase_admin
from firebase_admin import credentials
from flask import Flask, jsonify
from flask_cors import CORS

from routes.admin import admin_bp
from routes.ai import ai_bp
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.cities import cities_bp
from routes.inventory import inventory_bp
from routes.khata import khata_bp
from routes.notifications import notifications_bp
from routes.payments import payments_bp
from routes.profile import profile_bp
from routes.referrals import referrals_bp
from routes.reviews import reviews_bp
from routes.shops import shops_bp
from routes.subscriptions import subscriptions_bp
from routes.vendors import vendors_bp
from routes.wallet import wallet_bp


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("localshop.backend")


def _init_firebase() -> None:
    if firebase_admin._apps:  # idempotent
        return
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        firebase_admin.initialize_app(credentials.Certificate(cred_path))
        log.info("Initialized Firebase with service account at %s", cred_path)
    else:
        firebase_admin.initialize_app()
        log.info("Initialized Firebase with application default credentials")


_init_firebase()


def _register_legacy_blueprints(app: Flask) -> None:
    """Mount the previously-written grocery-shopping-app blueprints.

    These modules (`khata.py`, `wallet_routes.py`, `shop_wallet_routes.py`,
    `ratings.py`, `service_routes.py`, `service_notifications_routes.py`)
    target a different Firestore schema and carry heavier dependencies
    (razorpay, reportlab, weasyprint). They are registered on a best-effort
    basis: if imports fail (missing deps, missing credentials) the primary
    API still comes up cleanly.
    """

    legacy = (
        # (module path, attribute name, optional url_prefix)
        ("khata", "khata_bp", "/api/khata"),
        ("wallet_routes", "wallet_bp", None),
        ("shop_wallet_routes", "shop_wallet_bp", None),
        ("ratings", "ratings_bp", None),
        ("service_routes", "service_bp", "/service"),
        ("service_notifications_routes", "service_notifications_bp", None),
    )
    import importlib

    for module_name, attr, prefix in legacy:
        try:
            module = importlib.import_module(module_name)
            bp = getattr(module, attr)
        except Exception as exc:  # pragma: no cover - legacy best-effort
            log.warning("Skipping legacy blueprint %s (%s): %s", module_name, attr, exc)
            continue
        try:
            if prefix:
                app.register_blueprint(bp, url_prefix=prefix)
            else:
                app.register_blueprint(bp)
            log.info("Registered legacy blueprint %s", module_name)
        except Exception as exc:  # pragma: no cover - legacy best-effort
            log.warning("Failed to register legacy blueprint %s: %s", module_name, exc)


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    for bp in (
        auth_bp,
        shops_bp,
        cities_bp,
        vendors_bp,
        admin_bp,
        chat_bp,
        notifications_bp,
        subscriptions_bp,
        ai_bp,
        referrals_bp,
        inventory_bp,
        reviews_bp,
        payments_bp,
        wallet_bp,
        khata_bp,
        profile_bp,
    ):
        app.register_blueprint(bp)

    _register_legacy_blueprints(app)

    @app.get("/")
    def index():
        return jsonify({"ok": True, "service": "localshop-finder-backend"})

    @app.get("/health")
    def health():
        return jsonify({"status": "healthy"})

    @app.errorhandler(404)
    def not_found(_err):
        return jsonify({"detail": "Route not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_err):
        return jsonify({"detail": "Method not allowed"}), 405

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
