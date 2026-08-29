"""Publish this pod's MCP server.json to the in-cluster MCP registry.

Uses only the stdlib so it can run as a postStart hook inside the
official agent-sandbox MCP image and the mcp-server-fetch image.
Anonymous auth is enabled on the POC registry
(io.modelcontextprotocol.anonymous/*).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _wait_http(url: str, attempts: int, delay: float) -> None:
    last = "not attempted"
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if 200 <= resp.status < 500:
                    return
                last = f"status={resp.status}"
        except Exception as exc:  # noqa: BLE001 — hook must keep retrying
            last = str(exc)
        time.sleep(delay)
        print(f"waiting for {url} ({i + 1}/{attempts}): {last}", flush=True)
    raise SystemExit(f"timeout waiting for {url}: {last}")


def _json_request(method: str, url: str, body: dict | None, token: str | None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8") or "{}") if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            parsed = {"error": raw.decode("utf-8", errors="replace")}
        return exc.code, parsed


def _first_ok(urls: list[str], method: str, body: dict | None, token: str | None):
    last_status, last_body = 0, {}
    for url in urls:
        status, payload = _json_request(method, url, body, token)
        print(f"{method} {url} -> {status}", flush=True)
        if status < 400:
            return status, payload
        last_status, last_body = status, payload
        blob = json.dumps(payload).lower()
        if status == 409 or "already exists" in blob or "already published" in blob:
            return status, payload
    return last_status, last_body


def main() -> int:
    registry = _env("MCP_REGISTRY_URL", "http://mcp-registry:8080").rstrip("/")
    server_json_path = _env("MCP_SERVER_JSON", "/config/server.json")
    local_ready = _env("MCP_WAIT_LOCAL", "http://127.0.0.1:8000/readyz")

    print(f"register: registry={registry} server_json={server_json_path}", flush=True)

    _wait_http(f"{registry}/v0.1/health", attempts=60, delay=2.0)
    if local_ready:
        _wait_http(local_ready, attempts=60, delay=2.0)

    with open(server_json_path, encoding="utf-8") as fh:
        server = json.load(fh)

    status, token_body = _first_ok(
        [f"{registry}/v0/auth/none", f"{registry}/v0.1/auth/none"],
        "POST",
        {},
        None,
    )
    token = (
        token_body.get("registry_token")
        or token_body.get("token")
        or token_body.get("access_token")
        or ""
    )
    if status >= 400 or not token:
        print(f"anonymous auth failed: {status} {token_body}", flush=True)
        return 1

    status, published = _first_ok(
        [f"{registry}/v0.1/publish", f"{registry}/v0/publish"],
        "POST",
        server,
        token,
    )
    print(f"publish result {status}: {json.dumps(published)[:500]}", flush=True)
    if status >= 400 and status != 409:
        return 1
    print("registered with MCP registry", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
