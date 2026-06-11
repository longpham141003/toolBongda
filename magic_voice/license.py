"""
license.py — Hệ thống License Key cho MagicVoice TTS Studio
- Key gắn với phần cứng máy (MAC + hostname + CPU)
- Không cần internet để validate
- Key sai / hết hạn → app không chạy
"""

import hashlib, hmac, uuid, platform, socket, json, os, time
from pathlib import Path
from datetime import datetime, timedelta

# ── Khóa bí mật ──────────────────────────────────────────────────
# Visual CapCut chỉ dùng MagicVoice như engine clone voice local, không dùng hệ
# thống license GUI gốc. Không hard-code secret vào repo; nếu cần chạy GUI gốc
# với license riêng thì cấu hình qua biến môi trường.
_SECRET = os.environ.get("MAGICVOICE_LICENSE_SECRET", "VisualCapCutLocalLicense").encode("utf-8")
_LICENSE_FILE = Path(__file__).resolve().parent / ".license"
_APP_NAME = "MagicVoice TTS Studio"
_VERSION  = "2.0"

# ── Lấy fingerprint phần cứng ─────────────────────────────────────
def get_machine_id() -> str:
    """Tạo fingerprint duy nhất cho máy này."""
    parts = []

    # MAC address (ổn định nhất)
    try:
        mac = uuid.getnode()
        parts.append(f"mac:{mac:012x}")
    except Exception:
        pass

    # Hostname
    try:
        parts.append(f"host:{socket.gethostname().lower()}")
    except Exception:
        pass

    # Processor
    try:
        cpu = platform.processor() or platform.machine()
        parts.append(f"cpu:{cpu[:40]}")
    except Exception:
        pass

    # Windows machine GUID (nếu có)
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography")
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            parts.append(f"guid:{guid}")
            winreg.CloseKey(key)
        except Exception:
            pass

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Tạo key từ machine_id ─────────────────────────────────────────
def generate_key(machine_id: str, days: int = 0,
                 note: str = "") -> str:
    """
    Tạo license key cho 1 máy.
    days=0 → vĩnh viễn
    days>0 → hết hạn sau N ngày
    """
    expiry = ""
    if days > 0:
        exp_date = datetime.now() + timedelta(days=days)
        expiry = exp_date.strftime("%Y%m%d")
    else:
        expiry = "99991231"  # Vĩnh viễn

    # Payload = machine_id + expiry
    payload = f"{machine_id}|{expiry}"
    # HMAC-SHA256 với secret key
    sig = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:24]

    # Format key: XXXX-XXXX-XXXX-XXXX-XXXX-XXXX
    sig_upper = sig.upper()
    key = "-".join(sig_upper[i:i+4] for i in range(0, 24, 4))
    return f"{key}|{expiry}"


# ── Validate key ──────────────────────────────────────────────────
def validate_key(key_str: str, machine_id: str) -> tuple[bool, str]:
    """
    Kiểm tra key có hợp lệ không.
    """
    if not os.environ.get("MAGICVOICE_LICENSE_SECRET"):
        return False, "MagicVoice GUI license chưa được cấu hình. Visual CapCut clone voice vẫn chạy local."
    try:
        key_part, expiry = key_str.strip().split("|", 1)
        payload = f"{machine_id}|{expiry}"
        expected = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:24].upper()
        expected_key = "-".join(expected[i:i+4] for i in range(0, 24, 4))
        if key_part.upper() != expected_key:
            return False, "License không hợp lệ."
        if expiry != "99991231" and datetime.now().strftime("%Y%m%d") > expiry:
            return False, "License đã hết hạn."
        return True, "License hợp lệ."
    except Exception as exc:
        return False, f"License lỗi định dạng: {exc}"


# ── Lưu / đọc license file ────────────────────────────────────────
def save_license(key_str: str):
    """Lưu license đã kích hoạt."""
    data = {
        "key":        key_str,
        "machine_id": get_machine_id(),
        "activated":  datetime.now().isoformat(),
        "app":        _APP_NAME,
    }
    # Mã hóa đơn giản bằng XOR với secret hash
    raw    = json.dumps(data)
    secret = hashlib.sha256(_SECRET).hexdigest()
    enc    = bytes(ord(c) ^ ord(secret[i % len(secret)])
                   for i, c in enumerate(raw))
    _LICENSE_FILE.write_bytes(enc)


def load_license() -> dict | None:
    """Đọc license đã lưu."""
    if not _LICENSE_FILE.exists():
        return None
    try:
        enc    = _LICENSE_FILE.read_bytes()
        secret = hashlib.sha256(_SECRET).hexdigest()
        raw    = "".join(chr(b ^ ord(secret[i % len(secret)]))
                         for i, b in enumerate(enc))
        return json.loads(raw)
    except Exception:
        return None


# ── Check tổng thể ────────────────────────────────────────────────
def check_activation() -> tuple[bool, str]:
    """
    Kiểm tra xem app đã được kích hoạt chưa.
    """
    if not os.environ.get("MAGICVOICE_LICENSE_SECRET"):
        return False, "MagicVoice GUI license chưa được cấu hình. Visual CapCut clone voice vẫn chạy local."
    data = load_license()
    if not data:
        return False, "Chưa kích hoạt license."
    if data.get("machine_id") != get_machine_id():
        return False, "License không thuộc máy này."
    return validate_key(str(data.get("key", "")), get_machine_id())


# ── CLI: Dùng để tạo key (chỉ bạn chạy) ─────────────────────────
if __name__ == "__main__":
    import sys

    print("=" * 55)
    print(f"  {_APP_NAME} — License Key Generator")
    print("=" * 55)

    if len(sys.argv) == 1:
        # Chạy không có arg → xem machine_id máy hiện tại
        mid = get_machine_id()
        print(f"\n  Machine ID may nay: {mid}")
        print(f"\n  Dung lenh sau de tao key:")
        print(f"  python license.py gen <machine_id> [days] [note]")
        print(f"\n  Vi du:")
        print(f"  python license.py gen {mid} 0       <- vinh vien")
        print(f"  python license.py gen {mid} 365     <- 1 nam")

    elif sys.argv[1] == "gen" and len(sys.argv) >= 3:
        machine_id = sys.argv[2]
        days       = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        note       = sys.argv[4] if len(sys.argv) > 4 else ""
        key        = generate_key(machine_id, days, note)
        print(f"\n  Machine ID : {machine_id}")
        print(f"  Thoi han   : {'Vinh vien' if days==0 else f'{days} ngay'}")
        print(f"  Ghi chu    : {note or '(khong co)'}")
        print(f"\n  +== LICENSE KEY =====+")
        print(f"  |  {key}")
        print(f"  +====================+")
        print(f"\n  Gui key nay cho khach hang.")

    elif sys.argv[1] == "revoke" and len(sys.argv) >= 3:
        machine_id = sys.argv[2]
        key        = generate_revoke_key(machine_id)
        print(f"\n  Machine ID : {machine_id}")
        print(f"  Loai       : KEY THU HOI (het han ngay lap tuc)")
        print(f"\n  +== KEY THU HOI ==+")
        print(f"  |  {key}")
        print(f"  +=================+")
        print(f"\n  Gui key nay cho khach de vo hieu hoa.")

    elif sys.argv[1] == "check":
        ok, msg = check_activation()
        mid = get_machine_id()
        print(f"\n  Machine ID : {mid}")
        print(f"  Trang thai: {msg}")

    elif sys.argv[1] == "activate":
        if len(sys.argv) < 3:
            print("  Dung: python license.py activate <KEY>")
        else:
            key = sys.argv[2]
            mid = get_machine_id()
            ok, msg = validate_key(key, mid)
            if ok:
                save_license(key)
                print(f"\n  {msg}")
                print(f"  Da luu license thanh cong!")
            else:
                print(f"\n  LOI: {msg}")
    else:
        print("  Lenh: gen | check | activate")
