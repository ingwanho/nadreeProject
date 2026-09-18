import math
from threading import Lock

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import GoogleAuthError
from google.cloud import firestore

from app.errors import Problem


class VehicleLocations:
    def __init__(self, settings):
        self.project = settings.firestore_project
        self.client = None
        self.lock = Lock()

    def get(self, sensor_code):
        if not self.project:
            raise Problem(503, "LOCATION_NOT_CONFIGURED")
        if not sensor_code or "/" in sensor_code:
            raise Problem(409, "SENSOR_CODE_INVALID")
        try:
            with self.lock:
                if self.client is None:
                    self.client = firestore.Client(project=self.project)
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
