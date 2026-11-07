"""Network-address rules shared by every source resolver.

Deliberately one implementation. This is the SSRF guard, and the failure mode
of copying it is that a fallback resolver quietly reaches an internal address
the primary resolver refuses to - the fallback path being the one nobody
exercises until it matters.

Two layers, because checking a URL and fetching it are different moments:

1. `validate_public_url` parses the URL, resolves the host and refuses any
   address that is not public. It returns the address it approved.
2. `build_public_opener` returns a urllib opener whose HTTP/HTTPS handlers
   re-run that check for every request they open (the first one and every
   redirect hop) and then connect to the *approved address* rather than
   resolving the hostname a second time. Checking at one moment and resolving
   again at another is the DNS-rebinding hole: a name can answer a public
   address to the check and a private one to the fetch. Pinning closes it.
   The Host header and TLS server name still come from the URL, so
   certificate verification is unchanged.

Messages here follow the user/operator split `UserFacingError` sets out: what
`str(exc)` says has to read on a phone, and anything only an operator can act
on goes to `log_detail`.
"""

import functools
import http.client
import ipaddress
import socket
import urllib.request
from urllib.parse import urlparse

from ...domain.errors import MediaValidationError

MAX_URL_LENGTH = 2048

# IPv6 ranges that carry an IPv4 address inside them. `is_global` judges the
# IPv6 address, which for NAT64 (RFC 6052 / RFC 8215) is "global" even when the
# embedded IPv4 is 127.0.0.1, so the embedded address has to be checked too.
_NAT64_PREFIXES = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 address stands for, if it is a translation
    form (IPv4-mapped, 6to4, Teredo, NAT64)."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    for prefix in _NAT64_PREFIXES:
        if ip in prefix:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_public_address(value: str) -> bool:
    """True only for an address on the public internet: not loopback, private,
    link-local, multicast, reserved or unspecified - and, for IPv6, not a
    translation form wrapping a non-public IPv4 address either."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not ip.is_global or ip.is_multicast:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_ipv4(ip)
        if inner is not None and not inner.is_global:
            return False
    return True


def _parse(url: str) -> tuple[str, int]:
    if len(url) > MAX_URL_LENGTH:
        raise MediaValidationError("That link is too long.")
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise MediaValidationError("Enter a valid public http:// or https:// link.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise MediaValidationError("Enter a valid public http:// or https:// link.") from exc
    return parsed.hostname, port


def resolve_public_address(hostname: str, port: int) -> str:
    """Resolve `hostname` and return its first address, refusing the whole
    name if *any* of its addresses is not public. The returned address is the
    one a pinned connection should use."""
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError) as exc:
        raise MediaValidationError(
            "That link's site couldn't be found - check for a typo.", log_detail=str(exc)
        ) from exc
    if not addresses:
        raise MediaValidationError("That link's site couldn't be found - check for a typo.")
    for address in addresses:
        if not is_public_address(address[4][0]):
            raise MediaValidationError("That link points to a private network address.")
    return addresses[0][4][0]


def validate_public_url(url: str) -> str:
    """Reject anything that is not a plain public HTTP(S) address.

    Resolves the host and checks every address it maps to, so a hostname that
    points at loopback or link-local space is refused even though it looks
    external. Returns the approved address so a caller can connect to exactly
    what was checked (see `build_public_opener`).
    """
    hostname, port = _parse(url)
    return resolve_public_address(hostname, port)


# ---------------------------------------------------------------- pinning

def _connect_pinned(conn: http.client.HTTPConnection, address: str) -> None:
    """`HTTPConnection.connect`, but to the approved address. `conn.host`
    keeps the name from the URL, which is what goes in the Host header and
    the TLS server name."""
    conn.sock = socket.create_connection(
        (address, conn.port), conn.timeout, conn.source_address
    )
    try:
        conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    if conn._tunnel_host:  # noqa: SLF001 - stdlib's own connect does the same
        conn._tunnel()  # noqa: SLF001


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, pinned_address: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pinned_address = pinned_address

    def connect(self) -> None:
        _connect_pinned(self, self.pinned_address)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, pinned_address: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pinned_address = pinned_address

    def connect(self) -> None:
        _connect_pinned(self, self.pinned_address)
        server_hostname = self._tunnel_host or self.host  # noqa: SLF001 - as stdlib
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)  # noqa: SLF001


def _pinned_connection_class(request: urllib.request.Request, connection_class):
    """Check the request's URL and return a connection factory bound to the
    approved address. Raises `MediaValidationError` for a non-public target.

    Through an explicit proxy (urllib's ProxyHandler, from HTTP(S)_PROXY) the
    proxy does the resolving and the connection goes to it, so the URL is
    still checked but the connection is not pinned - pinning the proxy's own
    address would be wrong, and the proxy is the operator's.
    """
    address = validate_public_url(request.full_url)
    if request.has_proxy():
        return connection_class.__mro__[1]  # the plain stdlib class
    return functools.partial(connection_class, pinned_address=address)


class PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_pinned_connection_class(req, PinnedHTTPConnection), req)


class PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(
            _pinned_connection_class(req, PinnedHTTPSConnection), req, context=self._context
        )


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-runs the public-address check on every redirect hop.

    Validating only the URL the caller typed is not enough: a public host is
    free to redirect to `http://169.254.169.254/`, and following that blindly
    is the classic way an SSRF guard gets walked straight past. The open
    handlers above check (and pin) again when the redirected request is
    opened; this check runs first so the refusal is raised before any
    connection is attempted.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_public_opener() -> urllib.request.OpenerDirector:
    """The opener every outbound urllib fetch uses: public addresses only,
    checked and pinned per request, redirects re-checked."""
    return urllib.request.build_opener(PublicHTTPHandler, PublicHTTPSHandler, ValidatingRedirectHandler)
