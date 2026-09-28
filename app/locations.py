import math
from threading import Lock

try:
    from google.api_core.exceptions import GoogleAPICallError
    from google.auth.exceptions import GoogleAuthError
    from google.cloud import firestore
except ImportError:  # The health/docs process can run without the optional location SDK.
    firestore = None

    class GoogleAPICallError(Exception):
        pass

    class GoogleAuthError(Exception):
        pass

from app.errors import Problem


class VehicleLocations:
    def __init__(self, settings):
        self.settings = settings
        self.project = settings.location_firebase_project_id or settings.firestore_project
        self.client = None
        self.lock = Lock()

    def _credentials(self):
        settings = self.settings
        private_key = settings.location_firebase_private_key.get_secret_value()
        has_credentials = any((settings.location_firebase_client_email, private_key,
                               settings.location_firebase_private_key_id))
        if not has_credentials:
            return None
        if not (settings.location_firebase_project_id and settings.location_firebase_client_email and private_key):
            raise Problem(503, "LOCATION_NOT_CONFIGURED")
        try:
            from google.oauth2 import service_account
            return service_account.Credentials.from_service_account_info({
                "type": settings.location_firebase_credential_type,
                "project_id": settings.location_firebase_project_id,
                "private_key_id": settings.location_firebase_private_key_id,
                "private_key": private_key.replace("\\n", "\n"),
                "client_email": settings.location_firebase_client_email,
                "client_id": settings.location_firebase_client_id,
                "auth_uri": settings.location_firebase_auth_uri,
                "token_uri": settings.location_firebase_token_uri,
                "auth_provider_x509_cert_url": settings.location_firebase_auth_provider_x509_cert_url,
                "client_x509_cert_url": settings.location_firebase_client_x509_cert_url,
                "universe_domain": settings.location_firebase_universe_domain,
            })
        except (ImportError, TypeError, ValueError):
            raise Problem(503, "LOCATION_NOT_CONFIGURED") from None

    def get(self, sensor_code):
        if not self.project:
            raise Problem(503, "LOCATION_NOT_CONFIGURED")
        if firestore is None:
            raise Problem(503, "LOCATION_UNAVAILABLE")
        if not sensor_code or "/" in sensor_code:
            raise Problem(409, "SENSOR_CODE_INVALID")
        try:
            with self.lock:
                if self.client is None:
                    self.client = firestore.Client(project=self.project, credentials=self._credentials())
            document = self.client.collection("driving").document(sensor_code).get(timeout=5, retry=None)
            if not document.exists:
                raise Problem(404, "LOCATION_NOT_FOUND")
            data = document.to_dict()
            point = (data.get("g") or {}).get("geopoint")
            if point is None:
                raise Problem(404, "LOCATION_NOT_FOUND")
            lat, lng = float(point.latitude), float(point.longitude)
            if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise Problem(502, "LOCATION_DATA_INVALID")
            return {"lat": lat, "lng": lng}
        except (GoogleAuthError, GoogleAPICallError):
            raise Problem(503, "LOCATION_UNAVAILABLE") from None
        except (AttributeError, TypeError, ValueError):
            raise Problem(502, "LOCATION_DATA_INVALID") from None

    def close(self):
        if self.client is not None:
            self.client.close()
