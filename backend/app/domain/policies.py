import hashlib
import re

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


def is_valid_client_id(value: str) -> bool:
    return bool(CLIENT_ID_PATTERN.fullmatch(value))


def quota_key_from_headers(authorization: str, client_ip: str) -> str:
    # Keyed by IP, not the client-supplied X-Client-ID: that header is
    # self-reported and free to regenerate, so it carries no quota weight.
    if authorization.startswith("Bearer "):
        digest = hashlib.sha256(authorization.encode()).hexdigest()[:32]
        return f"token:{digest}"
    return f"ip:{client_ip}" if client_ip else "anonymous"
