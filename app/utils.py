import re
import unicodedata
from datetime import datetime, timedelta

def norm_text(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return value.lower().strip()

def norm_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("33"):
        digits = "0" + digits[2:]
    return digits

def hhmm_to_minutes(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 60 + int(m)

def minutes_to_hhmm(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"

def new_id(prefix: str) -> str:
    return f"{prefix}-{int(datetime.utcnow().timestamp()*1000)}"
