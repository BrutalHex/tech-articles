"""Shared agent-sandbox claim helpers used by code tools."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_sandbox_lock = threading.Lock()
_sandbox_client = None
_sandbox_handle = None
_logger = logging.getLogger(__name__)


def use_agent_sandbox() -> bool:
    """
    Whether sandbox features (claim / history) should talk to agent-sandbox.

    code_interpreter always uses agent-sandbox and does not in-process exec.
    History listing still gates on this flag so non-cluster unit tests can skip
    live claims when SANDBOX_BACKEND=local.
    """
    backend = os.getenv("SANDBOX_BACKEND", "auto").strip().lower()
    if backend in {"agent-sandbox", "k8s", "sandbox"}:
        return True
    if backend in {"local", "inline", "exec"}:
        return False
    # auto: prefer agent-sandbox when running inside Kubernetes
    return Path("/var/run/secrets/kubernetes.io/serviceaccount/token").exists()


def get_sandbox_client():
    global _sandbox_client
    if _sandbox_client is not None:
        return _sandbox_client

    from k8s_agent_sandbox import SandboxClient
    from k8s_agent_sandbox.models import (
        SandboxDirectConnectionConfig,
        SandboxInClusterConnectionConfig,
        SandboxLocalTunnelConnectionConfig,
    )

    mode = os.getenv("SANDBOX_CONNECTION_MODE", "in-cluster").strip().lower()
    if mode in {"in-cluster", "incluster", "cluster"}:
        connection_config = SandboxInClusterConnectionConfig()
    elif mode in {"tunnel", "local", "dev"}:
        connection_config = SandboxLocalTunnelConnectionConfig()
    elif mode in {"direct", "router"}:
        api_url = os.getenv(
            "SANDBOX_ROUTER_URL",
            "http://sandbox-router-svc.agent-sandbox-system.svc.cluster.local:8080",
        )
        connection_config = SandboxDirectConnectionConfig(api_url=api_url)
    else:
        connection_config = SandboxInClusterConnectionConfig()

    _sandbox_client = SandboxClient(connection_config=connection_config, cleanup=False)
    return _sandbox_client


_CLAIM_LABELS = {
    "app.kubernetes.io/part-of": "agentic-chain",
    "app.kubernetes.io/component": "code-interpreter",
}
_CLAIM_LABEL_SELECTOR = (
    "app.kubernetes.io/part-of=agentic-chain,"
    "app.kubernetes.io/component=code-interpreter"
)


def _handle_is_ready(handle) -> bool:
    """Return True when a sandbox handle is active and reports Ready."""
    if handle is None or not getattr(handle, "is_active", False):
        return False
    try:
        status, _message = handle.status()
        return status == "SandboxReady"
    except Exception:
        return False


def _reattach_existing_claim(client, namespace: str, timeout: int):
    """
    Reuse an existing labeled SandboxClaim if one is still Ready.

    Critical on low-memory hosts: process restarts must not claim a new warm
    spare (each claim leaves an extra sandbox pod until TTL expiry).
    """
    try:
        claim_names = client.list_all_sandboxes(
            namespace=namespace,
            label_selector=_CLAIM_LABEL_SELECTOR,
        )
    except Exception as exc:
        _logger.warning("list existing sandbox claims failed: %s", exc)
        return None

    for claim_name in sorted(claim_names or []):
        try:
            handle = client.get_sandbox(
                claim_name=claim_name,
                namespace=namespace,
                resolve_timeout=min(timeout, 30),
            )
            if _handle_is_ready(handle):
                _logger.info(
                    "Reattached to existing SandboxClaim %s in %s",
                    claim_name,
                    namespace,
                )
                return handle
            try:
                handle.terminate()
            except Exception:
                pass
        except Exception as exc:
            _logger.debug("skip claim %s: %s", claim_name, exc)
    return None


def claim_sandbox():
    """Claim (or reuse) a warm-pool sandbox for code execution + history."""
    global _sandbox_handle

    client = get_sandbox_client()
    warmpool = os.getenv("SANDBOX_WARMPOOL", "python-sandbox-warmpool")
    namespace = os.getenv("SANDBOX_NAMESPACE", "agentic-chain")
    shutdown_after = int(os.getenv("SANDBOX_SHUTDOWN_AFTER_SECONDS", "900"))
    timeout = int(os.getenv("SANDBOX_READY_TIMEOUT", "180"))

    with _sandbox_lock:
        if _handle_is_ready(_sandbox_handle):
            return _sandbox_handle
        if _sandbox_handle is not None:
            try:
                _sandbox_handle.terminate()
            except Exception:
                pass
            _sandbox_handle = None

        # Prefer reattaching an existing claim before consuming a warm spare.
        existing = _reattach_existing_claim(client, namespace, timeout)
        if existing is not None:
            _sandbox_handle = existing
            return _sandbox_handle

        # Only claim-level labels here. Avoid pod_labels that collide with the
        # SandboxTemplate (controller rejects overrides of existing keys).
        _sandbox_handle = client.create_sandbox(
            warmpool=warmpool,
            namespace=namespace,
            sandbox_ready_timeout=timeout,
            shutdown_after_seconds=shutdown_after if shutdown_after > 0 else None,
            labels=dict(_CLAIM_LABELS),
        )
        return _sandbox_handle


def _ensure_history_dir(sandbox) -> None:
    """Create /app/history in the sandbox (idempotent)."""
    try:
        sandbox.commands.run("mkdir -p history")
    except Exception as exc:
        _logger.warning("mkdir history failed: %s", exc)


def _write_sandbox_files(sandbox, files: dict[str, str]) -> None:
    """Write path→text pairs via files API, with shell fallback."""
    _ensure_history_dir(sandbox)
    try:
        for path, body in files.items():
            sandbox.files.write(path, body)
        return
    except Exception as exc:
        _logger.warning("files.write failed (%s); using shell fallback", exc)

    # Use python inside the sandbox to avoid shell quoting issues.
    assignments = "\n".join(
        f"Path({path!r}).write_text({body!r})" for path, body in files.items()
    )
    sandbox.commands.run(
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "Path('history').mkdir(parents=True, exist_ok=True)\n"
        f"{assignments}\n"
        "PY"
    )


def write_history(sandbox, code: str) -> dict:
    """
    Persist executed code under /app/history for later inspection.

    Returns a dict with shared basenames/paths so the caller can also write a
    companion result artifact after execution:
      {
        "base": "20260801T120000_abcd1234",
        "code_path": "history/....py",
        "meta_path": "history/....meta.json",
        "result_path": "history/....result.json",
      }
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    short_id = uuid.uuid4().hex[:8]
    base = f"{stamp}_{short_id}"
    code_path = f"history/{base}.py"
    meta_path = f"history/{base}.meta.json"
    result_path = f"history/{base}.result.json"
    code_body = code if code.endswith("\n") else code + "\n"
    meta_body = (
        json.dumps(
            {
                "path": code_path,
                "result_path": result_path,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "claim": sandbox.claim_name,
                "sandbox_id": sandbox.sandbox_id,
                "bytes": len(code_body.encode("utf-8")),
                "status": "pending",
            },
            indent=2,
        )
        + "\n"
    )

    _write_sandbox_files(
        sandbox,
        {
            code_path: code_body,
            meta_path: meta_body,
        },
    )
    return {
        "base": base,
        "code_path": code_path,
        "meta_path": meta_path,
        "result_path": result_path,
    }


def write_history_result(
    sandbox,
    history: dict,
    *,
    stdout: str,
    stderr: str,
    exit_code: int,
) -> str:
    """
    Persist execution result as a separate history artifact (.result.json)
    and refresh the companion .meta.json with exit status.
    """
    code_path = history["code_path"]
    meta_path = history["meta_path"]
    result_path = history["result_path"]
    created_at = datetime.now(timezone.utc).isoformat()
    result_obj = {
        "path": result_path,
        "code_path": code_path,
        "created_at": created_at,
        "claim": sandbox.claim_name,
        "sandbox_id": sandbox.sandbox_id,
        "exit_code": int(exit_code),
        "stdout": stdout or "",
        "stderr": stderr or "",
    }
    result_body = json.dumps(result_obj, indent=2) + "\n"
    meta_body = (
        json.dumps(
            {
                "path": code_path,
                "result_path": result_path,
                "created_at": created_at,
                "claim": sandbox.claim_name,
                "sandbox_id": sandbox.sandbox_id,
                "status": "ok" if int(exit_code) == 0 else "error",
                "exit_code": int(exit_code),
                "stdout_bytes": len((stdout or "").encode("utf-8")),
                "stderr_bytes": len((stderr or "").encode("utf-8")),
            },
            indent=2,
        )
        + "\n"
    )
    _write_sandbox_files(
        sandbox,
        {
            result_path: result_body,
            meta_path: meta_body,
        },
    )
    return result_path


def _entry_field(entry, key: str, default=None):
    if entry is None:
        return default
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _history_rel_path(name: str) -> str:
    """Normalize a list entry name to a path relative to the sandbox CWD."""
    name = str(name).strip().lstrip("./")
    if name.startswith("history/"):
        return name
    return f"history/{name}"


def _read_text(sandbox, rel_path: str) -> str | None:
    """Read a sandbox file via files API, then shell cat as fallback."""
    try:
        raw = sandbox.files.read(rel_path)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)
    except Exception as exc:
        _logger.debug("files.read %s failed: %s", rel_path, exc)

    try:
        # Avoid injecting untrusted path into the shell beyond basename under history/.
        base = Path(rel_path).name
        result = sandbox.commands.run(f"cat history/{base}")
        if getattr(result, "exit_code", 1) == 0:
            return (result.stdout or "")
    except Exception as exc:
        _logger.debug("shell cat %s failed: %s", rel_path, exc)
    return None


def _list_history_names(sandbox) -> list[dict]:
    """
    List *.py entries under history/.

    The runtime returns HTTP 404 for /list/history when the directory does not
    exist yet — the SDK surfaces that as a communication error. Treat missing
    dir as empty and fall back to shell `ls` when needed.
    """
    _ensure_history_dir(sandbox)

    # Preferred: filesystem API
    try:
        entries = sandbox.files.list("history")
        out: list[dict] = []
        for entry in entries or []:
            name = _entry_field(entry, "name")
            if not name or not str(name).endswith(".py"):
                continue
            out.append(
                {
                    "name": Path(str(name)).name,
                    "size": _entry_field(entry, "size"),
                    "mod_time": _entry_field(entry, "mod_time"),
                }
            )
        return out
    except Exception as exc:
        _logger.info("files.list(history) failed (%s); using shell ls", exc)

    # Fallback: shell listing (works even when the list endpoint 404s)
    try:
        result = sandbox.commands.run(
            "ls -1 history/*.py 2>/dev/null | xargs -n1 basename 2>/dev/null || true"
        )
        names = [
            line.strip()
            for line in (result.stdout or "").splitlines()
            if line.strip().endswith(".py")
        ]
        return [{"name": n, "size": None, "mod_time": None} for n in names]
    except Exception as exc:
        _logger.warning("shell ls history failed: %s", exc)
        return []


def fetch_code_execution_history(limit: int = 50) -> dict:
    """
    Return structured history from the claimed agent-sandbox
    (code + meta + result artifacts).

    Shape:
      {
        "ok": bool,
        "error": str | None,
        "claim": str | None,
        "sandbox_id": str | None,
        "count": int,
        "entries": [
          {
            "name": "...py",
            "meta_name": "...meta.json",
            "result_name": "...result.json",
            "size": int | None,
            "mod_time": ...,
            "code": str | None,
            "meta": str | None,   # raw meta.json text
            "meta_obj": dict | None,
            "result": str | None,  # raw result.json text
            "result_obj": dict | None,
          },
          ...
        ],
      }
    """
    if not use_agent_sandbox():
        return {
            "ok": False,
            "error": "History is only available when SANDBOX_BACKEND=agent-sandbox.",
            "claim": None,
            "sandbox_id": None,
            "count": 0,
            "entries": [],
        }

    try:
        sandbox = claim_sandbox()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Error claiming sandbox for history: {exc}",
            "claim": None,
            "sandbox_id": None,
            "count": 0,
            "entries": [],
        }

    try:
        listed = _list_history_names(sandbox)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Error listing code history: {exc}",
            "claim": getattr(sandbox, "claim_name", None),
            "sandbox_id": getattr(sandbox, "sandbox_id", None),
            "count": 0,
            "entries": [],
        }

    files: list[dict] = []
    for entry in listed:
        base = Path(str(entry["name"])).name
        stem = base[: -len(".py")] if base.endswith(".py") else base
        py_rel = _history_rel_path(base)
        meta_base = f"{stem}.meta.json"
        meta_rel = _history_rel_path(meta_base)
        result_base = f"{stem}.result.json"
        result_rel = _history_rel_path(result_base)

        code = _read_text(sandbox, py_rel)
        meta_text = _read_text(sandbox, meta_rel)
        result_text = _read_text(sandbox, result_rel)
        meta_obj = None
        if meta_text:
            try:
                meta_obj = json.loads(meta_text)
            except Exception:
                meta_obj = None
        result_obj = None
        if result_text:
            try:
                result_obj = json.loads(result_text)
            except Exception:
                result_obj = None

        files.append(
            {
                "name": base,
                "meta_name": meta_base,
                "result_name": result_base,
                "size": entry.get("size"),
                "mod_time": entry.get("mod_time"),
                "code": code,
                "meta": meta_text,
                "meta_obj": meta_obj,
                "result": result_text,
                "result_obj": result_obj,
            }
        )

    files.sort(key=lambda item: item.get("mod_time") or 0, reverse=True)
    if limit and int(limit) > 0:
        files = files[: int(limit)]
    return {
        "ok": True,
        "error": None,
        "claim": sandbox.claim_name,
        "sandbox_id": sandbox.sandbox_id,
        "count": len(files),
        "entries": files,
    }


def list_code_execution_history(limit: int = 50) -> str:
    """
    List code-execution history (filenames + full source + meta) as JSON text.
    Used by the LangChain tool so the model must quote real tool output.
    """
    data = fetch_code_execution_history(limit=limit)
    if not data.get("ok"):
        return data.get("error") or "Error listing code history."
    if not data.get("entries"):
        return (
            "No code-execution history found yet. "
            "Run code via code_interpreter first, then re-check history."
        )

    # Compact but complete payload for the LLM (includes full code + results).
    payload = {
        "claim": data["claim"],
        "sandbox_id": data["sandbox_id"],
        "count": data["count"],
        "files": [
            {
                "name": e["name"],
                "meta_name": e["meta_name"],
                "result_name": e.get("result_name"),
                "size": e.get("size"),
                "mod_time": e.get("mod_time"),
                "code": e.get("code") or "",
                "meta": e.get("meta_obj") or e.get("meta"),
                "result": e.get("result_obj") or e.get("result"),
            }
            for e in data["entries"]
        ],
        "instruction": (
            "Return ONLY these sandbox history entries to the user. "
            "Quote each script's code and result stdout/stderr. Do NOT invent "
            "revenue, regulations, or any facts not present in this JSON."
        ),
    }
    return json.dumps(payload, indent=2)


def reset_sandbox_handle_for_tests() -> None:
    """Test helper: drop the cached claim handle."""
    global _sandbox_handle
    with _sandbox_lock:
        _sandbox_handle = None


__all__ = [
    "claim_sandbox",
    "fetch_code_execution_history",
    "get_sandbox_client",
    "list_code_execution_history",
    "reset_sandbox_handle_for_tests",
    "use_agent_sandbox",
    "write_history",
    "write_history_result",
    "_logger",
]
