"""yt-dlp's side of the SSRF guard: every request it makes goes through `net.py`.

Checking only the URL the user submitted leaves yt-dlp free to do its own DNS
lookups, follow redirects and fetch whatever the page points at (manifests,
segments, embedded media, subtitle tracks). `GuardedYoutubeDL` closes that in
two places, both of which reuse `net.py` rather than copying it:

1. **Requests.** The request director holds exactly one handler,
   `PublicUrllibRH`: yt-dlp's urllib handler with its HTTP(S) connections
   swapped for `net.py`'s pinned ones. Each connection - the first request,
   every redirect hop, every fragment - resolves the host with
   `validate_public_url` at connect time and dials the approved address, so a
   redirect or a DNS rebind cannot reach a private address. The `requests`,
   `websockets` and `curl_cffi` handlers are left out because their
   connections are made inside third-party code this module cannot pin; ftp
   and file URLs are not supported at all.
2. **Downloaders.** Only native downloaders run (`_NATIVE_DOWNLOADERS`), and
   each of them fetches through `ydl.urlopen`, i.e. through (1). yt-dlp would
   otherwise hand a remote URL to ffmpeg (live HLS/DASH, the HLS fallback for
   manifests the native downloader cannot play, `m3u8` formats) or rtmpdump,
   and those open their own sockets. `hls_prefer_native` keeps ordinary HLS
   on the native path; anything that would still need ffmpeg is refused.

Through an explicit proxy (yt-dlp's `proxy` option or `HTTP(S)_PROXY` /
`ALL_PROXY`, socks included) the URL of every request and redirect hop is
still checked but the connection goes to the proxy unpinned, the same policy
`net.py` applies: the proxy does the resolving, and it is the operator's.
"""

import functools
import urllib.request
from urllib.request import (
    DataHandler,
    HTTPCookieProcessor,
    HTTPDefaultErrorHandler,
    HTTPErrorProcessor,
    UnknownHandler,
)

import yt_dlp.downloader.hls as _hls
from yt_dlp import YoutubeDL
from yt_dlp.downloader import get_suitable_downloader
from yt_dlp.downloader.dash import DashSegmentsFD
from yt_dlp.downloader.external import FFmpegFD
from yt_dlp.downloader.f4m import F4mFD
from yt_dlp.downloader.hls import HlsFD
from yt_dlp.downloader.http import HttpFD
from yt_dlp.downloader.ism import IsmFD
from yt_dlp.networking._urllib import HTTPHandler, ProxyHandler, RedirectHandler, UrllibRH
from yt_dlp.networking.exceptions import RequestError
from yt_dlp.utils import DownloadError

from ...domain.errors import MediaValidationError
from .net import PinnedHTTPConnection, PinnedHTTPSConnection, validate_public_url

# Downloaders whose every byte comes through `ydl.urlopen`. FFmpegFD, RtmpFD,
# the websocket/live downloaders and the external ones (aria2c, curl, wget...)
# open their own connections and are refused.
_NATIVE_DOWNLOADERS = frozenset({HttpFD, HlsFD, DashSegmentsFD, F4mFD, IsmFD})

# yt-dlp's own header for "this request goes through a socks proxy"; its HTTP
# handler pops it to build the socks connection.
_SOCKS_HEADER = "Ytdl-socks-proxy"


class _PublicHTTPHandler(HTTPHandler):
    """yt-dlp's HTTP handler (header handling, decompression) with `net.py`'s
    check-and-pin at connect time."""

    def _open_public(self, req, connection_class, super_open, **kwargs):
        if req.has_proxy() or req.has_header(_SOCKS_HEADER):
            validate_public_url(req.full_url)
            return super_open(req)
        address = validate_public_url(req.full_url)
        source = (self._source_address, 0) if self._source_address else None
        factory = functools.partial(connection_class, pinned_address=address, source_address=source)
        return self.do_open(factory, req, **kwargs)

    def http_open(self, req):
        return self._open_public(req, PinnedHTTPConnection, super().http_open)

    def https_open(self, req):
        return self._open_public(
            req, PinnedHTTPSConnection, super().https_open, context=self._context
        )


class _PublicRedirectHandler(RedirectHandler):
    """Refuses a redirect to a non-public or non-HTTP(S) target before the
    hop is attempted. Without a proxy the open handler checks again (and
    pins) when the hop connects; through a proxy this is the only check."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PublicUrllibRH(UrllibRH):
    _SUPPORTED_URL_SCHEMES = ("http", "https", "data")

    def __init__(self, **kwargs) -> None:
        kwargs["enable_file_urls"] = False
        super().__init__(**kwargs)

    def _create_instance(self, proxies, cookiejar, legacy_ssl_support=None):
        # UrllibRH's handler list with the guarded HTTP and redirect handlers,
        # and without FTPHandler / FileHandler.
        guarded = urllib.request.OpenerDirector()
        for handler in (
            ProxyHandler(proxies),
            _PublicHTTPHandler(
                debuglevel=int(bool(self.verbose)),
                context=self._make_sslcontext(legacy_ssl_support=legacy_ssl_support),
                source_address=self.source_address,
            ),
            HTTPCookieProcessor(cookiejar),
            DataHandler(),
            UnknownHandler(),
            HTTPDefaultErrorHandler(),
            HTTPErrorProcessor(),
            _PublicRedirectHandler(),
        ):
            guarded.add_handler(handler)
        guarded.addheaders = []
        return guarded

    def _send(self, request):
        # yt-dlp's director treats anything that is not a RequestError as a
        # handler bug and logs it as one; a refusal is an ordinary failure.
        try:
            return super()._send(request)
        except MediaValidationError as exc:
            raise RequestError(f"Refused by the SSRF guard: {exc}", cause=exc) from exc


class _RefusedFFmpegFD(FFmpegFD):
    """Stands in for FFmpegFD inside HlsFD, which hands a manifest it cannot
    play natively to ffmpeg. ffmpeg would fetch it with its own sockets."""

    def real_download(self, filename, info_dict):
        self.report_error("This stream needs ffmpeg to download it, which is disabled.")
        return False


# HlsFD looks FFmpegFD up as a module global at the moment it falls back, so
# the substitution has to happen there. Fail closed (the worker refuses to
# import) if a yt-dlp release moves it, rather than silently re-opening it.
if getattr(_hls, "FFmpegFD", None) is not FFmpegFD:
    raise ImportError("yt_dlp.downloader.hls.FFmpegFD moved; re-check ytdlp_net.py")
_hls.FFmpegFD = _RefusedFFmpegFD


class GuardedYoutubeDL(YoutubeDL):
    """The only YoutubeDL this app constructs. See the module docstring."""

    def __init__(self, params=None, *args, **kwargs) -> None:
        params = {**(params or {}), "hls_prefer_native": True}
        params.pop("external_downloader", None)
        super().__init__(params, *args, **kwargs)

    def build_request_director(self, handlers, preferences=None):
        return super().build_request_director([PublicUrllibRH], preferences)

    def dl(self, name, info, subtitle=False, test=False):
        # The same choice `YoutubeDL.dl` is about to make; a format check
        # (`test=True`) runs with yt-dlp's stripped-down test params.
        params = {"test": True} if test else self.params
        downloader = get_suitable_downloader(dict(info), params, to_stdout=(name == "-"))
        if downloader not in _NATIVE_DOWNLOADERS:
            label = getattr(downloader, "__name__", downloader)
            raise DownloadError(f"Refusing the {label} downloader: it fetches outside the SSRF guard.")
        return super().dl(name, info, subtitle=subtitle, test=test)
