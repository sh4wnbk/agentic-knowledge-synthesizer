"""
start_bridge.py
One command to start the bridge and sync the YAML with the live tunnel URL.

Usage:
    python start_bridge.py
"""

import json
import re
import subprocess
import sys
import time
import urllib.request

YAML_PATH = "orchestrate/skill_bridge_openapi.yaml"
NGROK_API  = "http://localhost:4040/api/tunnels"
PORT       = 8080


def get_ngrok_url(retries: int = 6, delay: float = 1.5) -> str:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(NGROK_API, timeout=5) as r:
                data   = json.load(r)
                tunnel = next(
                    (t for t in data["tunnels"] if t["proto"] == "https"),
                    data["tunnels"][0]
                )
                return tunnel["public_url"]
        except Exception:
            time.sleep(delay)
    raise RuntimeError("ngrok did not start in time — check that it is installed.")


def update_yaml(url: str) -> None:
    with open(YAML_PATH) as f:
        content = f.read()
    updated = re.sub(r"(url:\s+)https?://\S+", f"\\g<1>{url}", content)
    with open(YAML_PATH, "w") as f:
        f.write(updated)


def main() -> None:
    print("\n" + "═" * 52)
    print("  AEGIS SKILL BRIDGE — STARTUP")
    print("═" * 52)

    print("[1/3] Starting uvicorn on port 8080...")
    uvicorn = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "orchestrate.skill_server:app",
         "--host", "0.0.0.0", "--port", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    print("[2/3] Starting ngrok tunnel...")
    ngrok = subprocess.Popen(
        ["ngrok", "http", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print("[3/3] Reading tunnel URL from ngrok API...")
    try:
        url = get_ngrok_url()
    except RuntimeError as e:
        print(f"\n  ERROR: {e}")
        uvicorn.terminate()
        ngrok.terminate()
        sys.exit(1)

    update_yaml(url)

    print()
    print("═" * 52)
    print("  BRIDGE ACTIVE")
    print(f"  URL:   {url}")
    print(f"  YAML:  {YAML_PATH}  (updated)")
    print()
    print("  In Orchestrate:")
    print("    1. Toolset → delete intentRoute + crisisBrief")
    print("    2. Add tool → Import from file → skill_bridge_openapi.yaml")
    print("═" * 52)
    print("\n  Ctrl+C to shut down.\n")

    try:
        uvicorn.wait()
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        uvicorn.terminate()
        ngrok.terminate()


if __name__ == "__main__":
    main()
