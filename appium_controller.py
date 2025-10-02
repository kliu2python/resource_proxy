import requests


def _normalise_server(server: str) -> str:
    return server.rstrip("/")

def start_appium_session(
    server: str,
    device_id: str,
    platform: str,
    version: str,
    wda_local_port: int | None = None,
) -> str:
    first_match = {
        "platformName": platform,
        "platformVersion": version,
        "deviceName": device_id,
        "automationName": "UiAutomator2" if platform == "android" else "XCUITest",
    }
    if platform == "ios" and wda_local_port:
        first_match["wdaLocalPort"] = int(wda_local_port)

    payload = {"capabilities": {"firstMatch": [first_match]}}
    base = _normalise_server(server)
    resp = requests.post(f"{base}/session", json=payload, timeout=60)
    resp.raise_for_status()
    val = resp.json().get("value", {})
    sid = val.get("sessionId") or resp.json().get("sessionId")
    if not sid:
        raise RuntimeError(f"Cannot parse Appium sessionId from: {resp.text}")
    return sid

def stop_appium_session(server: str, session_id: str) -> None:
    base = _normalise_server(server)
    requests.delete(f"{base}/session/{session_id}", timeout=30)
