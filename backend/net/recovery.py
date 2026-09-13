from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import psutil

LOGGER = logging.getLogger(__name__)
QUIC_RULE_NAME = "NetworkInspector-Block-QUIC"


def is_admin() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def remove_quic_rule() -> bool:
    if os.name != "nt":
        return True
    current = _run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "show",
            "rule",
            f"name={QUIC_RULE_NAME}",
        ]
    )
    if QUIC_RULE_NAME.casefold() not in current.stdout.casefold():
        return True
    result = _run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "delete",
            "rule",
            f"name={QUIC_RULE_NAME}",
        ]
    )
    ok = result.returncode == 0
    if not ok:
        LOGGER.error("QUIC kuralı kaldırılamadı: %s", result.stderr.strip())
    return ok


def read_runtime_state(runtime_dir: Path) -> dict[str, Any]:
    state_file = runtime_dir / "state.json"
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def process_is_alive(pid: int | None, expected_start_time: float | None = None) -> bool:
    if not pid:
        return False
    try:
        process = psutil.Process(pid)
        if process.status() == psutil.STATUS_ZOMBIE:
            return False
        if expected_start_time is not None:
            return abs(process.create_time() - expected_start_time) < 0.01
        return True
    except psutil.AccessDenied:
        return True
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
def write_runtime_state(runtime_dir: Path, state: dict[str, Any]) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    target = runtime_dir / "state.json"
    temporary = runtime_dir / "state.json.tmp"
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(target)


def cleanup_stale_state(runtime_dir: Path) -> dict[str, Any]:
    previous = read_runtime_state(runtime_dir)
    rule_removed = remove_quic_rule()
    state_file = runtime_dir / "state.json"
    try:
        state_file.unlink(missing_ok=True)
    except OSError:
        LOGGER.exception("Stale runtime durumu silinemedi")
    return {"previous_state": previous, "quic_rule_removed": rule_removed}


def verify_network_configuration() -> dict[str, Any]:
    result: dict[str, Any] = {"system_proxy_modified": False}
    if os.name == "nt":
        proxy = _run(
            [
                "reg",
                "query",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                "/v",
                "ProxyEnable",
            ]
        )
        result["proxy_check_ok"] = proxy.returncode == 0
        result["proxy_state"] = proxy.stdout.strip()
    return result
