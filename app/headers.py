from fastapi import Depends, Header
from fastapi.security import HTTPBearer

bearer = Depends(HTTPBearer(auto_error=False))


def refresh_header(x_refresh_token: str | None = Header(default=None, alias="X-Refresh-Token",
                   description="Required for refresh/logout and sensitive profile changes. Never use the query string.")):
    return x_refresh_token


def fcm_header(x_fcm_token: str | None = Header(default=None, alias="X-FCM-Token", max_length=512,
              description="Optional current device token; logout does not delete the stored token.")):
    return x_fcm_token
