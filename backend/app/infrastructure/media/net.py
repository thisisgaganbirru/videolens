"""Network-address rules shared by every source resolver.

Deliberately one implementation. This is the SSRF guard, and the failure mode
of copying it is that a fallback resolver quietly reaches an internal address
the primary resolver refuses to - the fallback path being the one nobody
exercises until it matters.
"""

import ipaddress
import socket
from urllib.parse import urlparse

from ...domain.errors import MediaValidationError

MAX_URL_LENGTH = 2048


def validate_public_url(url: str) -> None:
    """Reject anything that is not a plain public HTTP(S) address.

    Resolves the host and checks every address it maps to, so a hostname that
    points at loopback or link-local space is refused even though it looks
    external.
    """
    if len(url) > MAX_URL_LENGTH:
        raise MediaValidationError("URL is too long.")

    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise MediaValidationError("Enter a valid public HTTP or HTTPS media URL.")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError) as exc:
        raise MediaValidationError("The URL host could not be found.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise MediaValidationError("Local and private-network URLs are not allowed.")
