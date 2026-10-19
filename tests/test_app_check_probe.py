import httpx
import json

from scripts.verify_app_check import verify


def test_debug_probe_requires_success_and_enforcement():
    def handler(request):
        if "firebaseappcheck" in request.url.host:
            assert json.loads(request.content) == {"debugToken": "test-debug"}
            return httpx.Response(200, json={"token": "app-check-test"})
        if request.headers.get("X-Firebase-AppCheck") == "app-check-test":
            return httpx.Response(200, json={"result": {"unreadCount": 0}})
        return httpx.Response(401, json={"error": {"status": "UNAUTHENTICATED"}})
    config = {"projectNumber": "123", "appId": "1:123:web:abc", "apiKey": "test-api-key",
              "debugToken": "test-debug", "firebaseIdToken": "test-id"}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = verify(config, client)
    assert result["passed"] is True
    assert "test-debug" not in str(result) and "test-id" not in str(result)
