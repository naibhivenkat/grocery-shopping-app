"""LocalShop Finder backend entrypoint.

Flask application exposing the REST API consumed by the Flutter client in
`lib/features/**/data/datasources`. All endpoints are defined under feature
blueprints in the `routes/` package and persist data in Firestore under
`localshop/v1/<collection>`.
"""

import json
import logging
import os
import traceback

import firebase_admin
from firebase_admin import credentials
from flask import Flask, jsonify
from flask_cors import CORS

from routes.services import services_bp
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
from routes.smoke import smoke_bp
from routes.subscriptions import subscriptions_bp
from routes.support import support_bp
from routes.vendors import vendors_bp
from routes.wallet import wallet_bp
from routes.provider_profiles import provider_profiles_bp
from routes.bookings import bookings_bp
from routes.availability import availability_bp
from routes.service_wallet import service_wallet_bp

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


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    # Register exclusively V2 blueprints
    for bp in (
        auth_bp,
        shops_bp,
        cities_bp,
        vendors_bp,
        admin_bp,
        chat_bp,
        notifications_bp,
        subscriptions_bp,
        support_bp,
        ai_bp,
        referrals_bp,
        inventory_bp,
        reviews_bp,
        payments_bp,
        wallet_bp,
        khata_bp,
        profile_bp,
        smoke_bp,
        provider_profiles_bp,
        bookings_bp,
        availability_bp,
        service_wallet_bp,
        services_bp
    ):
        app.register_blueprint(bp)

    @app.errorhandler(Exception)
    def handle_exception(e):
        print("\n" + "=" * 80)
        print("UNHANDLED EXCEPTION")
        print("=" * 80)
        traceback.print_exc()
        print("=" * 80 + "\n")

        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500

    @app.get("/")
    def index():
        return jsonify({"ok": True, "service": "localshop-finder-backend-v2"})

    @app.get("/health")
    def health():
        return jsonify({"status": "healthy"})

    @app.errorhandler(404)
    def not_found(_err):
        return jsonify({"detail": "Route not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_err):
        return jsonify({"detail": "Method not allowed"}), 405

    @app.errorhandler(Exception)
    def on_unhandled(err):
        log.exception("Unhandled exception on %s", os.getenv("K_SERVICE", "local"))
        return jsonify({
            "detail": "Internal server error",
            "error": f"{type(err).__name__}: {err}",
            "trace": traceback.format_exc().splitlines()[-6:],
        }), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")