"""Test-only network guard. Ported verbatim from NextOneTwoLabs/ecnl-dashboard (#87 there) for
collegedash issue #345; .github/scripts/run_suite.py puts this directory on PYTHONPATH (with a dead proxy)
for every Python suite, locally and in CI.

Original notes (#87). Put this directory on PYTHONPATH and Python
imports it at start-up (as `sitecustomize`):

    PYTHONPATH=tests/netguard HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 \
        python -m unittest discover -s tests -p 'test_*.py'

It refuses every DNS lookup of a host that is not loopback (or this machine's own
name), every socket connection to an address that is not loopback, and every
connection to the proxy named in HTTPS_PROXY / HTTP_PROXY / ALL_PROXY (a request routed through the dead proxy is an attempt to reach the
internet too). Each attempt is recorded and printed. Because the refresh and
the club step swallow exceptions by design, a refused call alone could pass
unnoticed, so at exit the process fails with status 97 when anything was
attempted, whatever the tests reported. Local test servers on 127.0.0.1 are
unaffected. Set NETGUARD_REPORT=1 to print the attempt count even when it is 0.
"""
import atexit
import ipaddress
import os
import socket
import sys
import urllib.parse

NETGUARD_ACTIVE = True
EXIT_CODE = 97
ATTEMPTS = []
# http.server resolves the machine's own name when it binds (socket.getfqdn); a lookup
# of this host is not outbound traffic. Connections still need a loopback address.
_OWN_HOST = socket.gethostname().lower()


def _is_loopback(host):
    if host is None:
        return True                       # passive lookups (bind)
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    h = str(host).strip("[]").lower()
    if h in ("", "localhost") or h.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h.split("%")[0])
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


def _lookup_ok(host):
    h = host.decode("ascii", "replace") if isinstance(host, bytes) else host
    return _is_loopback(host) or str(h).lower() == _OWN_HOST


def _proxies():
    found = set()
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        value = os.environ.get(key)
        if not value:
            continue
        parts = urllib.parse.urlsplit(value if "://" in value else "http://" + value)
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            continue
        if parts.hostname:
            found.add((parts.hostname.lower(), port))
    return found


PROXIES = _proxies()


def _is_proxy(host, port):
    h = str(host).strip("[]").lower()
    return any(port == p and (h == ph or (_is_loopback(h) and _is_loopback(ph))) for ph, p in PROXIES)


def _refuse(kind, host, port):
    ATTEMPTS.append(f"{kind} {host}:{port}")
    sys.stderr.write(f"netguard: refused {kind} {host}:{port}\n")
    raise OSError(f"netguard: network blocked in tests ({kind} {host}:{port})")


def _check_address(kind, address):
    if isinstance(address, tuple) and len(address) >= 2:
        host, port = address[0], address[1]
        if not _is_loopback(host) or _is_proxy(host, port):
            _refuse(kind, host, port)


_getaddrinfo = socket.getaddrinfo
_gethostbyname = socket.gethostbyname
_gethostbyname_ex = socket.gethostbyname_ex
_gethostbyaddr = socket.gethostbyaddr
_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex


def getaddrinfo(host, port, *args, **kwargs):
    if not _lookup_ok(host):
        _refuse("DNS lookup", host, port)
    return _getaddrinfo(host, port, *args, **kwargs)


def gethostbyname(host):
    if not _lookup_ok(host):
        _refuse("DNS lookup", host, None)
    return _gethostbyname(host)


def gethostbyname_ex(host):
    if not _lookup_ok(host):
        _refuse("DNS lookup", host, None)
    return _gethostbyname_ex(host)


def gethostbyaddr(host):
    if not _lookup_ok(host):
        _refuse("reverse DNS lookup", host, None)
    return _gethostbyaddr(host)


def connect(self, address):
    _check_address("connection", address)
    return _connect(self, address)


def connect_ex(self, address):
    _check_address("connection", address)
    return _connect_ex(self, address)


socket.getaddrinfo = getaddrinfo
socket.gethostbyname = gethostbyname
socket.gethostbyname_ex = gethostbyname_ex
socket.gethostbyaddr = gethostbyaddr
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex


def _at_exit():
    if ATTEMPTS or os.environ.get("NETGUARD_REPORT"):
        sys.stderr.write(f"netguard: {len(ATTEMPTS)} network attempt(s) refused in this process\n")
    if ATTEMPTS:
        for line in ATTEMPTS[:20]:
            sys.stderr.write(f"netguard:   {line}\n")
        sys.stderr.write(f"netguard: failing the run (exit {EXIT_CODE}): a test reached for the network\n")
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:  # noqa: BLE001
                pass
        os._exit(EXIT_CODE)


atexit.register(_at_exit)   # registered first, so it runs last
