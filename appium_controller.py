import requests
from .config import APPIUM_SERVER

def start_appium_session(device_id: str, platform: str, version: str, wda_local_port: int | None = None) -> str:
    first_match = {
        "platformName": platform,
        "platformVersion": version,
        "deviceName": device_id,
        "automationName": "UiAutomator2" if platform == "android" else "XCUITest",
    }
    if platform == "ios" and wda_local_port:
        first_match["wdaLocalPort"] = int(wda_local_port)

    payload = {"capabilities": {"firstMatch": [first_match]}}
    resp = requests.post(f"{APPIUM_SERVER}/session", json=payload, timeout=60)
    resp.raise_for_status()
    val = resp.json().get("value", {})
    sid = val.get("sessionId") or resp.json().get("sessionId")
    if not sid:
        raise RuntimeError(f"Cannot parse Appium sessionId from: {resp.text}")
    return sid

def stop_appium_session(session_id: str) -> None:
    requests.delete(f"{APPIUM_SERVER}/session/{session_id}", timeout=30)
