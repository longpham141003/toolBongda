"""
auth_manager.py — Xac thuc qua API Server (an toan hon)
Khong can firebase_credentials.json tren may khach
"""
import hashlib, os, platform, uuid
from datetime import datetime, timedelta
from pathlib import Path
import json as _json

# ── Cau hinh API Server ───────────────────────────────────────────
_API_URL = os.environ.get("MAGICVOICE_API_URL", "").strip()
_API_KEY = os.environ.get("MAGICVOICE_API_KEY", "").strip()

# ── Machine ID ────────────────────────────────────────────────────
def get_machine_id() -> str:
    try:
        if platform.system() == "Windows":
            import subprocess
            result = subprocess.run(
                ["wmic", "csproduct", "get", "UUID"],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            uid = lines[-1] if len(lines) >= 2 else ""
            if uid and uid != "UUID" and len(uid) > 10:
                return hashlib.sha256(uid.encode()).hexdigest()[:32]
        mac  = hex(uuid.getnode())[2:].upper()
        host = platform.node()
        return hashlib.sha256(f"{mac}_{host}".encode()).hexdigest()[:32]
    except Exception:
        return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:32]

def _hash_pass(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# ── Xac thuc online qua API ───────────────────────────────────────
def verify_login(username: str, password: str) -> tuple:
    """Xac thuc qua API server neu duoc cau hinh.

    Visual CapCut chi dung MagicVoice engine local cho clone voice, khong can login
    GUI goc. Khong hard-code API key trong repo.
    """
    if not _API_URL or not _API_KEY:
        return False, "MagicVoice GUI login chua duoc cau hinh. Visual CapCut clone voice van chay local."
    return False, "MagicVoice GUI login bi tat trong ban tich hop Visual CapCut."

# ── Offline Cache ─────────────────────────────────────────────────
_OFFLINE_CACHE = Path(__file__).parent / ".offline_auth"
_OFFLINE_DAYS  = 7

def _save_offline_cache(username: str, password: str, msg: str):
    try:
        import base64
        exp = (datetime.now() + timedelta(days=_OFFLINE_DAYS)).isoformat()
        data = {
            "u":   username,
            "p":   _hash_pass(password),
            "msg": msg,
            "exp": exp,
            "mid": get_machine_id(),
        }
        encoded = base64.b64encode(_json.dumps(data).encode()).decode()
        _OFFLINE_CACHE.write_text(encoded, encoding="utf-8")
    except Exception:
        pass

def verify_login_offline(username: str, password: str):
    """Xac thuc offline cho GUI goc."""
    return False, "MagicVoice GUI offline login bi tat trong ban tich hop Visual CapCut."

def clear_offline_cache():
    try:
        if _OFFLINE_CACHE.exists():
            _OFFLINE_CACHE.unlink()
    except Exception:
        pass
