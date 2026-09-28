"""Firebase Authentication verification for Nadree customer login."""

import logging
from threading import Lock

from app.errors import Problem

logger = logging.getLogger(__name__)


class CustomerFirebaseAuth:
    """Verify customer ID tokens through the shared FCM Firebase project."""

    def __init__(self, settings, verify_fn=None):
        self.settings = settings
        self._verify_fn = verify_fn
        self._app = None
        self._lock = Lock()

    @property
    def configured(self):
        return self._verify_fn is not None or bool(
            self.settings.fcm_project_id
            and self.settings.fcm_client_email
            and self.settings.fcm_private_key.get_secret_value()
        )

    @property
    def required(self):
        return self.settings.env == "production"

    def _firebase_app(self):
        if not self.configured or self._verify_fn is not None:
            return None
        with self._lock:
            if self._app is not None:
                return self._app
            try:
                import firebase_admin
                from firebase_admin import credentials
            except ImportError as exc:
                raise Problem(503, "CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED") from exc
            info = {
                "type": self.settings.fcm_credential_type,
                "project_id": self.settings.fcm_project_id,
                "private_key_id": self.settings.fcm_private_key_id,
                "private_key": self.settings.fcm_private_key.get_secret_value().replace("\\n", "\n"),
                "client_email": self.settings.fcm_client_email,
                "client_id": self.settings.fcm_client_id,
                "auth_uri": self.settings.fcm_auth_uri,
                "token_uri": self.settings.fcm_token_uri,
                "auth_provider_x509_cert_url": self.settings.fcm_auth_provider_x509_cert_url,
                "client_x509_cert_url": self.settings.fcm_client_x509_cert_url,
                "universe_domain": self.settings.fcm_universe_domain,
            }
            try:
                self._app = firebase_admin.get_app("nadree-fcm")
            except ValueError:
                try:
                    self._app = firebase_admin.initialize_app(
                        credentials.Certificate(info),
                        {"projectId": self.settings.fcm_project_id},
                        name="nadree-fcm",
                    )
                except Exception as exc:
                    logger.error("Customer Firebase initialization failed: %s", type(exc).__name__)
                    raise Problem(503, "CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED") from exc
            return self._app

    def verify_uid(self, uid, id_token):
        """Verify the token and require its Firebase UID to match the request UID."""
        if not self.configured:
            if self.required:
                raise Problem(503, "CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED")
            # Development/test only. Production never reaches this branch.
            return {"uid": uid, "verified": False}
        if not id_token:
            raise Problem(401, "FIREBASE_ID_TOKEN_REQUIRED")
        try:
            if self._verify_fn is not None:
                claims = self._verify_fn(id_token)
            else:
                from firebase_admin import auth
                claims = auth.verify_id_token(id_token, app=self._firebase_app())
        except Problem:
            raise
        except Exception as exc:
            logger.info("Customer Firebase token rejected: %s", type(exc).__name__)
            raise Problem(401, "FIREBASE_ID_TOKEN_INVALID") from None
        if not isinstance(claims, dict):
            raise Problem(401, "FIREBASE_ID_TOKEN_INVALID")
        token_uid = claims.get("uid") or claims.get("sub")
        if token_uid != uid:
            raise Problem(401, "FIREBASE_UID_MISMATCH")
        return claims
