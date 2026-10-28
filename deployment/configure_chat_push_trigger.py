"""Read-only by default. Set retry policy on the single new approved function."""
import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx

PROJECT = "bail-472405"
REGION = "asia-southeast2"
FUNCTION = "dispatchChatPushEvent"
RESOURCE = f"projects/{PROJECT}/locations/{REGION}/functions/{FUNCTION}"
POLICY = "RETRY_POLICY_RETRY"
EXPECTED_ACCOUNT = "272033658852-compute@developer.gserviceaccount.com"


def checked_function(value):
    if (value.get("name") != RESOURCE or value.get("buildConfig", {}).get("entryPoint") != FUNCTION
            or value.get("buildConfig", {}).get("runtime") != "python312"
            or value.get("serviceConfig", {}).get("serviceAccountEmail") != EXPECTED_ACCOUNT):
        raise ValueError("Unexpected function identity")
    event = value.get("eventTrigger", {})
    filters = {item.get("attribute"): item for item in event.get("eventFilters", [])}
    document = filters.get("document", {})
    if (event.get("eventType") != "google.cloud.firestore.document.v1.created"
            or event.get("triggerRegion") != REGION
            or filters.get("database", {}).get("value") != "(default)"
            or document.get("value") != "chatPushEvents/{eventId}"
            or document.get("operator") != "match-path-pattern"):
        raise ValueError("Unexpected Firestore trigger")
    return event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--firebase-login-file", type=Path, required=True)
    args = parser.parse_args()
    result = {"project": PROJECT, "region": REGION, "function": FUNCTION, "apply": args.apply,
              "iam_changes": 0, "other_functions_changed": 0, "requests": []}
    try:
        root = Path(__file__).resolve().parents[1]
        login = json.loads(args.firebase_login_file.read_text())
        api = root / "chat/node_modules/firebase-tools/lib/api"
        script = "const a=require(process.argv[1]);process.stdout.write(JSON.stringify({client_id:a.clientId(),client_secret:a.clientSecret()}))"
        oauth = json.loads(subprocess.check_output(["node", "-e", script, str(api)], text=True))
        with httpx.Client(trust_env=False, timeout=30) as client:
            response = client.post("https://oauth2.googleapis.com/token", data={**oauth, "refresh_token":login["tokens"]["refresh_token"], "grant_type":"refresh_token"})
            result["requests"].append({"purpose":"login_token_refresh", "http_status":response.status_code})
            response.raise_for_status()
            headers = {"Authorization":"Bearer "+response.json()["access_token"]}
            url = "https://cloudfunctions.googleapis.com/v2/"+RESOURCE
            response = client.get(url, headers=headers)
            result["requests"].append({"purpose":"function_get", "http_status":response.status_code})
            response.raise_for_status()
            value = response.json()
            event = checked_function(value)
            result.update(state=value.get("state"), retry_policy_before=event.get("retryPolicy"))
            if args.apply and event.get("retryPolicy") != POLICY:
                response = client.patch(url, headers=headers, params={"updateMask":"eventTrigger.retryPolicy"},
                                        json={"name":RESOURCE,"eventTrigger":{"retryPolicy":POLICY}})
                result["requests"].append({"purpose":"set_new_function_retry_only", "http_status":response.status_code})
                response.raise_for_status()
                operation = response.json()
                deadline = time.monotonic()+360
                while not operation.get("done"):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Retry-policy update is still running")
                    time.sleep(3)
                    response = client.get("https://cloudfunctions.googleapis.com/v2/"+operation["name"], headers=headers)
                    response.raise_for_status()
                    operation = response.json()
                if operation.get("error"):
                    result["operation_error_code"] = operation["error"].get("code")
                    raise RuntimeError("Retry-policy operation failed")
            response = client.get(url, headers=headers)
            response.raise_for_status()
            event = checked_function(response.json())
            result["retry_policy_after"] = event.get("retryPolicy")
            if args.apply and event.get("retryPolicy") != POLICY:
                raise RuntimeError("Retry policy was not applied")
            result["status"] = "verified" if event.get("retryPolicy") == POLICY else "configuration_required"
    except Exception as exc:
        result.update(status="stopped",exception_type=type(exc).__name__)
        if isinstance(exc,httpx.HTTPStatusError):
            try:
                result["error_code"] = exc.response.json().get("error",{}).get("status")
            except ValueError:
                pass
    print(json.dumps(result))
    return 0 if result["status"] in ("verified","configuration_required") else 1


if __name__ == "__main__":
    raise SystemExit(main())
