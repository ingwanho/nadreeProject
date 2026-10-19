"""Read-only debug-provider smoke test; never prints tokens or response bodies."""
import argparse
import json
import re
import stat
from pathlib import Path

import httpx


def verify(config, client):
    number, app_id = config["projectNumber"], config["appId"]
    if not re.fullmatch(r"[0-9]+", number) or not re.fullmatch(r"1:[0-9]+:(android|ios|web):[a-zA-Z0-9]+", app_id):
        raise ValueError("invalid app identifiers")
    if app_id.split(":")[1] != number:
        raise ValueError("project/app mismatch")
    exchange = client.post(f"https://firebaseappcheck.googleapis.com/v1/projects/{number}/apps/{app_id}:exchangeDebugToken",
        headers={"X-Goog-Api-Key": config["apiKey"]}, json={"debugToken": config["debugToken"]})
    if exchange.status_code != 200:
        return {"exchange": exchange.status_code, "passed": False}
    token = exchange.json()["token"]
    endpoint = "https://asia-southeast2-bail-472405.cloudfunctions.net/getChatUnreadSummary"
    results = {}
    for name, app_token in (("valid", token), ("missing", None), ("invalid", "invalid-app-check-token")):
        headers = {"Authorization": "Bearer " + config["firebaseIdToken"]}
        if app_token is not None:
            headers["X-Firebase-AppCheck"] = app_token
        response = client.post(endpoint, headers=headers, json={"data": config.get("data", {})})
        success = response.status_code == 200 and "result" in response.json() if name == "valid" else response.status_code == 401
        results[name] = {"httpStatus": response.status_code, "passed": success}
    return {"checks": results, "passed": all(item["passed"] for item in results.values())}


def main():
    parser = argparse.ArgumentParser(description="App Check debug token + authenticated read-only callable test")
    parser.add_argument("config", type=Path, help="private JSON file (0600); never commit")
    args = parser.parse_args()
    try:
        if stat.S_IMODE(args.config.stat().st_mode) & 0o077:
            raise ValueError("config must be private")
        config = json.loads(args.config.read_text())
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            result = verify(config, client)
        print(json.dumps(result))
        return 0 if result["passed"] else 1
    except Exception:
        # Network exceptions can contain credential-bearing URLs; do not dump them.
        print('{"passed": false, "error": "APP_CHECK_TEST_CONFIGURATION_OR_NETWORK_ERROR"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
