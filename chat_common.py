#!/usr/bin/env python3
"""Shared helpers/constants for TuiOS chat."""

from __future__ import annotations

import json
import datetime as dt
from pathlib import Path
from typing import Any

THIS_FILE = Path(__file__).resolve()
ROOT_DIR = THIS_FILE.parent

CHAT_PORT = 50555
PEERS_FILE = ROOT_DIR / "chat_peers.json"
LOG_FILE = ROOT_DIR / "chat_history.jsonl"
SELF_FILE = ROOT_DIR / "chat_self.json"

DEFAULT_PEERS: dict[str, str] = {"127.0.0.1": "local"}
DEFAULT_SELF = {"nickname": "me"}


def ensure_peers_file() -> None:
    if PEERS_FILE.exists():
        return
    PEERS_FILE.write_text(json.dumps(DEFAULT_PEERS, indent=2) + "\n", encoding="utf-8")


def ensure_self_file() -> None:
    if SELF_FILE.exists():
        return
    SELF_FILE.write_text(json.dumps(DEFAULT_SELF, indent=2) + "\n", encoding="utf-8")


def _load_peers_from_obj(obj: Any) -> dict[str, str]:
    peers: dict[str, str] = {}
    if isinstance(obj, dict):
        if "allowed" in obj and isinstance(obj["allowed"], list):
            for entry in obj["allowed"]:
                if not isinstance(entry, dict):
                    continue
                ip = str(entry.get("ip", "")).strip()
                nickname = str(entry.get("nickname", "")).strip()
                if ip and nickname:
                    peers[ip] = nickname
            return peers
        for key, value in obj.items():
            if isinstance(value, str) and key:
                peers[str(key).strip()] = value.strip()
        return peers
    if isinstance(obj, list):
        for entry in obj:
            if not isinstance(entry, dict):
                continue
            ip = str(entry.get("ip", "")).strip()
            nickname = str(entry.get("nickname", "")).strip()
            if ip and nickname:
                peers[ip] = nickname
    return peers


def load_peers() -> dict[str, str]:
    ensure_peers_file()
    try:
        raw = PEERS_FILE.read_text(encoding="utf-8")
        obj = json.loads(raw)
    except Exception:
        return dict(DEFAULT_PEERS)
    peers = _load_peers_from_obj(obj)
    return peers or dict(DEFAULT_PEERS)


def load_self_nickname() -> str:
    ensure_self_file()
    try:
        raw = SELF_FILE.read_text(encoding="utf-8")
        obj = json.loads(raw)
    except Exception:
        return DEFAULT_SELF["nickname"]
    if isinstance(obj, dict):
        nickname = str(obj.get("nickname", "")).strip()
        if nickname:
            return nickname
    return DEFAULT_SELF["nickname"]


def peer_name(ip: str, peers: dict[str, str] | None = None) -> str:
    if peers is None:
        peers = load_peers()
    return peers.get(ip, ip)


def append_log(entry: dict[str, Any]) -> None:
    entry = dict(entry)
    entry.setdefault("timestamp", dt.datetime.now().isoformat(timespec="seconds"))
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log(max_entries: int | None = None) -> list[dict[str, Any]]:
    if not LOG_FILE.exists():
        return []
    entries: list[dict[str, Any]] = []
    for raw in LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    if max_entries is not None and max_entries > 0:
        return entries[-max_entries:]
    return entries
