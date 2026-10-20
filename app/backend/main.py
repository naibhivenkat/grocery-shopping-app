"""LocalShop Finder backend entrypoint.

Flask application exposing the REST API consumed by the Flutter client in
`lib/features/**/data/datasources`. All endpoints are defined under feature
blueprints in the `routes/` package and persist data in Firestore under
`localshop/v1/<collection>`.
"""

import json
import logging
import os

import firebase_admin
from firebase_admin import credentials
from flask import Flask, jsonify
from flask_cors import CORS


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("localshop.backend")


def _init_firebase() -> None:
    if firebase_admin._apps:  # idempotent
        return

    options = {}
    storage_bucket = os.getenv("FIREBASE_STORAGE_BUCKET")
    if storage_bucket:
        options["storageBucket"] = storage_bucket

    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        try:
            service_account = json.loads(cred_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "FIREBASE_CREDENTIALS_JSON is not valid JSON"
            ) from exc

        project_id = service_account.get("project_id")
        if project_id:
            options["projectId"] = project_id
        firebase_admin.initialize_app(
            credentials.Certificate(service_account),
            options,
        )
        log.info(
            "Initialized Firebase with service account JSON for project %s",
            project_id,
        )
        return

    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        firebase_admin.initialize_app(credentials.Certificate(cred_path), options)
        log.info("Initialized Firebase with service account at %s", cred_path)
    else:
        project_id = os.getenv("FIREBASE_PROJECT_ID")
        if project_id:
            options["projectId"] = project_id
        firebase_admin.initialize_app(options=options or None)
        log.info("Initialized Firebase with application default credentials")


_init_firebase()


# Import route modules only after Firebase has been initialized.  The V2
# routes use lazy Firestore access, while optional legacy modules still have
# import-time Firebase assumptions.  Keeping initialization first prevents a
# Gunicorn worker from crashing during boot and leaving Cloud Run at its
# generic 503 response.
from routes.admin import admin_bp
from routes.ai import ai_bp
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.cities import cities_bp
from routes.inventory import inventory_bp
from routes.billing import billing_bp
from routes.product_import import product_import_bp
from routes.khata import khata_bp
from routes.notifications import notifications_bp
from routes.payments import payments_bp
from routes.razorpay_api import razorpay_api_bp
from routes.profile import profile_bp
from routes.promotions import promotions_bp
from routes.order_refunds import order_refunds_bp
from routes.media import media_bp
from routes.referrals import referrals_bp
from routes.reviews import reviews_bp
from routes.shops import shops_bp
from routes.shop_applications import shop_applications_bp
from routes.order_amendments import order_amendments_bp
from routes.checkout_abandon import checkout_abandon_bp
from routes.advertisements import advertisements_bp
from routes.smoke import smoke_bp
from routes.support import support_bp
from routes.gmail_admin import gmail_admin_bp
from routes.subscriptions import subscriptions_bp
from routes.google_play import google_play_bp
from routes.vendors import vendors_bp
from routes.wallet import wallet_bp
from routes.provider_profiles import provider_profiles_bp
from routes.services import services_bp
from routes.availability import availability_bp
from routes.bookings import bookings_bp
from routes.service_wallet import service_wallet_bp
from razorpay_webhook import razorpay_webhook_bp


def _register_legacy_blueprints(app: Flask) -> None:
    """Mount the previously-written grocery-shopping-app blueprints.

    These modules (`khata.py`, `wallet_routes.py`, `shop_wallet_routes.py`,
    `ratings.py`, `service_routes.py`, `service_notifications_routes.py`)
    target a different Firestore schema and carry heavier dependencies
    (razorpay, reportlab, weasyprint). They are registered on a best-effort
    basis: if imports fail (missing deps, missing credentials) the primary
    API still comes up cleanly.
    """

    if os.getenv("ENABLE_LEGACY_ROUTES", "0") != "1":
        log.info("Legacy blueprints disabled; using authenticated V2 routes")
        return

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
        shop_applications_bp,
        order_amendments_bp,
        checkout_abandon_bp,
        advertisements_bp,
        cities_bp,
        vendors_bp,
        admin_bp,
        chat_bp,
        notifications_bp,
        subscriptions_bp,
        google_play_bp,
        ai_bp,
        referrals_bp,
        inventory_bp,
        billing_bp,
        product_import_bp,
        reviews_bp,
        payments_bp,
        razorpay_api_bp,
        wallet_bp,
        khata_bp,
        profile_bp,
        promotions_bp,
        order_refunds_bp,
        media_bp,
        smoke_bp,
        support_bp,
        gmail_admin_bp,
        provider_profiles_bp,
        services_bp,
        availability_bp,
        bookings_bp,
        service_wallet_bp,
        razorpay_webhook_bp,
    ):
        app.register_blueprint(bp)

    _register_legacy_blueprints(app)

    @app.get("/")
    def index():
        return jsonify({"ok": True, "service": "localshop-finder-backend"})

    @app.get("/health")
    def health():
        return jsonify({"status": "healthy"})

    @app.get("/features")
    def features():
        return jsonify({"wallet_enabled": False, "promotions_enabled": True,
                        "promotion_billing": "free", "khata_vendor_confirmed": True,
                        "backend_contract_version": 2,
                        "subscription_contract_version": 1, "vendor_subscriptions_admin_managed": True,
                        "subscription_enforcement_capabilities": ["catalog_growth", "product_import", "promotions"],
                        "release": os.getenv("BACKEND_RELEASE", "local")})

    @app.before_request
    def disabled_wallet():
        from flask import request
        # Preserve historic balances and payment settlement; block new wallet use.
        if request.path.startswith(("/wallet", "/service-wallet")) and request.method != "OPTIONS":
            return jsonify({"detail": "Wallet is temporarily disabled",
                            "code": "WALLET_DISABLED"}), 410
        # Existing APK action requests send JSON Content-Type with no body.
        # Preserve those actions while rejecting malformed/non-object bodies.
        if request.is_json and request.get_data() and request.method in {"POST", "PUT", "PATCH"}:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"detail": "A valid JSON object is required"}), 422

    @app.errorhandler(404)
    def not_found(_err):
        return jsonify({"detail": "Route not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_err):
        return jsonify({"detail": "Method not allowed"}), 405

    @app.errorhandler(Exception)
    def on_unhandled(err):
        from werkzeug.exceptions import HTTPException
        if isinstance(err, HTTPException):
            return jsonify({"detail": err.description}), err.code
        log.exception("Unhandled exception on %s", os.getenv("K_SERVICE", "local"))
        return jsonify({"detail": "Internal server error"}), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
