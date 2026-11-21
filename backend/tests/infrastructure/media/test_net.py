import http.client
import ipaddress
import socket
import unittest
import urllib.request
from unittest.mock import MagicMock, patch

from app.domain.errors import MediaValidationError
from app.infrastructure.media.net import (
    MAX_URL_LENGTH,
    PinnedHTTPConnection,
    PinnedHTTPSConnection,
    PublicHTTPHandler,
    PublicHTTPSHandler,
    ValidatingRedirectHandler,
    _embedded_ipv4,
    _pinned_connection_class,
    build_public_opener,
    is_public_address,
    validate_public_url,
)


class PublicUrlValidationTests(unittest.TestCase):
    """The SSRF guard, tested where it lives now that both the yt-dlp and the
    direct-HTTP resolver share this one implementation."""

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_accepts_public_https_url(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

        validate_public_url("https://example.com/video/123")

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_rejects_private_network_target(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

        with self.assertRaisesRegex(MediaValidationError, "private network"):
            validate_public_url("http://localhost/media")

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_rejects_a_host_whose_second_address_is_private(self, getaddrinfo) -> None:
        # Every resolved address has to pass, not just the first one.
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
        ]

        with self.assertRaisesRegex(MediaValidationError, "private network"):
            validate_public_url("https://dual.test/clip.mp4")

    def test_rejects_non_http_url(self) -> None:
        with self.assertRaisesRegex(MediaValidationError, "http:// or https://"):
            validate_public_url("file:///etc/passwd")

    def test_rejects_embedded_credentials(self) -> None:
        with self.assertRaisesRegex(MediaValidationError, "http:// or https://"):
            validate_public_url("https://user:pw@example.com/clip.mp4")

    def test_rejects_an_overlong_url(self) -> None:
        with self.assertRaisesRegex(MediaValidationError, "too long"):
            validate_public_url("https://example.com/" + "a" * MAX_URL_LENGTH)

    @patch("app.infrastructure.media.net.socket.getaddrinfo", side_effect=socket.gaierror)
    def test_reports_an_unresolvable_host(self, _dns) -> None:
        with self.assertRaisesRegex(MediaValidationError, "couldn't be found"):
            validate_public_url("https://nope.invalid/clip.mp4")


class AddressClassificationTests(unittest.TestCase):
    """`is_public_address` is what the guard asks of every resolved address.
    The translation forms are the interesting cases: `ipaddress` judges the
    IPv6 side, which for NAT64 is "global" even when the embedded IPv4 is
    loopback - the gap that let `64:ff9b::7f00:1` through."""

    def test_public_v4_and_v6(self) -> None:
        self.assertTrue(is_public_address("8.8.8.8"))
        self.assertTrue(is_public_address("2606:4700::1111"))

    def test_private_loopback_and_link_local(self) -> None:
        for address in ("127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "fe80::1", "fc00::1", "0.0.0.0"):
            self.assertFalse(is_public_address(address), address)

    def test_ipv4_mapped_and_nat64_wrapping_a_private_address(self) -> None:
        for address in ("::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "64:ff9b:1::7f00:1"):
            self.assertFalse(is_public_address(address), address)

    def test_nat64_wrapping_a_public_address_is_still_public(self) -> None:
        self.assertTrue(is_public_address("64:ff9b::808:808"))

    def test_ipv4_compatible_and_translated_forms_wrapping_loopback(self) -> None:
        # `ipaddress` calls both of these global.
        for address in ("::127.0.0.1", "::ffff:0:7f00:1", "::ffff:0:a9fe:a9fe", "::10.0.0.1"):
            self.assertFalse(is_public_address(address), address)

    def test_translated_form_wrapping_a_public_address_is_still_public(self) -> None:
        self.assertTrue(is_public_address("::ffff:0:808:808"))

    def test_garbage_is_not_public(self) -> None:
        self.assertFalse(is_public_address("not-an-ip"))


class EmbeddedIPv4Tests(unittest.TestCase):
    """Each translation form `_embedded_ipv4` unwraps. 6to4 and Teredo are
    already non-global to `ipaddress`, so these pin the unwrapping itself."""

    def _inner(self, value: str):
        return _embedded_ipv4(ipaddress.IPv6Address(value))

    def test_ipv4_mapped(self) -> None:
        self.assertEqual(self._inner("::ffff:10.0.0.1"), ipaddress.IPv4Address("10.0.0.1"))

    def test_6to4(self) -> None:
        self.assertEqual(self._inner("2002:7f00:1::"), ipaddress.IPv4Address("127.0.0.1"))

    def test_teredo_client_address(self) -> None:
        # Teredo stores the client address bit-inverted in the low 32 bits.
        self.assertEqual(
            self._inner("2001:0:4136:e378::80ff:fffe"), ipaddress.IPv4Address("127.0.0.1")
        )

    def test_nat64_compatible_and_translated(self) -> None:
        for value in ("64:ff9b::7f00:1", "::127.0.0.1", "::ffff:0:7f00:1"):
            self.assertEqual(self._inner(value), ipaddress.IPv4Address("127.0.0.1"), value)

    def test_a_plain_ipv6_address_embeds_nothing(self) -> None:
        self.assertIsNone(self._inner("2606:4700::1111"))


class PinnedConnectionTests(unittest.TestCase):
    """The resolve-then-fetch race: the address the guard approved is the one
    the socket connects to, instead of resolving the name a second time."""

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_validate_returns_the_approved_address(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        self.assertEqual(validate_public_url("https://example.com/clip.mp4"), "93.184.216.34")

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_opener_binds_the_connection_to_the_approved_address(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        request = urllib.request.Request("http://example.com/clip.mp4")

        factory = _pinned_connection_class(request, PinnedHTTPConnection)
        connection = factory("example.com", timeout=5)

        self.assertIsInstance(connection, PinnedHTTPConnection)
        self.assertEqual(connection.pinned_address, "93.184.216.34")
        self.assertEqual(connection.host, "example.com")  # Host header / SNI keep the name

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_opener_refuses_a_private_target_before_connecting(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))]
        request = urllib.request.Request("http://internal.example/secret")

        with self.assertRaisesRegex(MediaValidationError, "private network"):
            _pinned_connection_class(request, PinnedHTTPConnection)

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_connect_dials_the_pinned_address_not_the_name(self, create_connection) -> None:
        connection = PinnedHTTPConnection("example.com", 80, timeout=3, pinned_address="93.184.216.34")

        connection.connect()

        create_connection.assert_called_once_with(("93.184.216.34", 80), 3, None)

    @patch("app.infrastructure.media.net.socket.create_connection")
    def test_https_connect_dials_the_pinned_address_and_keeps_the_server_name(
        self, create_connection
    ) -> None:
        context = MagicMock()
        connection = PinnedHTTPSConnection(
            "example.com", 443, timeout=3, context=context, pinned_address="93.184.216.34"
        )

        connection.connect()

        create_connection.assert_called_once_with(("93.184.216.34", 443), 3, None)
        # The handshake is run after the TLS socket is tracked by the download
        # deadline (test_download_deadline.py), so it is not done on wrap.
        context.wrap_socket.assert_called_once_with(
            create_connection.return_value, server_hostname="example.com", do_handshake_on_connect=False
        )
        self.assertIs(connection.sock, context.wrap_socket.return_value)
        context.wrap_socket.return_value.do_handshake.assert_called_once_with()

    @patch("app.infrastructure.media.net.socket.getaddrinfo")
    def test_proxied_request_is_checked_but_not_pinned(self, getaddrinfo) -> None:
        # The proxy resolves the name; pinning the proxy's own socket to the
        # media host's address would send the request to the wrong place.
        getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        request = urllib.request.Request("http://example.com/clip.mp4")
        request.set_proxy("proxy.internal:3128", "http")

        factory = _pinned_connection_class(request, PinnedHTTPConnection)

        self.assertIs(factory, http.client.HTTPConnection)

    def test_public_opener_uses_the_checking_handlers(self) -> None:
        opener = build_public_opener()
        kinds = {type(handler) for handler in opener.handlers}
        self.assertIn(PublicHTTPHandler, kinds)
        self.assertIn(PublicHTTPSHandler, kinds)
        self.assertIn(ValidatingRedirectHandler, kinds)
        self.assertNotIn(urllib.request.HTTPHandler, kinds)
        self.assertNotIn(urllib.request.HTTPSHandler, kinds)


if __name__ == "__main__":
    unittest.main()
