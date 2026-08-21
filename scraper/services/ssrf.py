"""SSRF protection for every outbound scraper request."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.google.com",
        "169.254.169.254",
        "metadata.aws.internal",
    }
)
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


class RequestPolicyError(ValueError):
    """The URL or redirect target is not allowed."""


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    hostname: str
    addresses: tuple[str, ...]


def _is_blocked_ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return True
    if any(addr in network for network in _BLOCKED_NETWORKS):
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast


def validate_url(url: str, *, resolve: bool = True) -> ValidatedURL:
    if not url or not str(url).strip():
        raise RequestPolicyError("A URL is required.")
    raw = str(url).strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise RequestPolicyError("Only http and https URLs are allowed.")
    if parsed.username or parsed.password:
        raise RequestPolicyError("URLs must not contain embedded credentials.")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise RequestPolicyError("The URL is missing a hostname.")
    if hostname in _BLOCKED_HOSTS or hostname.endswith(".localhost"):
        raise RequestPolicyError("That host is not allowed.")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if _is_blocked_ip(hostname):
            raise RequestPolicyError("Private or reserved addresses are not allowed.")

    addresses: list[str] = []
    if resolve:
        try:
            infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise RequestPolicyError("The hostname could not be resolved.") from exc
        for info in infos:
            addr = info[4][0]
            addresses.append(addr)
            if _is_blocked_ip(addr):
                raise RequestPolicyError("The hostname resolves to a private or reserved address.")
        if not addresses:
            raise RequestPolicyError("The hostname could not be resolved.")

    clean = urlunparse((parsed.scheme, parsed.netloc.split("@")[-1], parsed.path or "/", parsed.params, parsed.query, ""))
    return ValidatedURL(url=clean, hostname=hostname, addresses=tuple(dict.fromkeys(addresses)))


def validate_redirect(previous: ValidatedURL, next_url: str) -> ValidatedURL:
    return validate_url(next_url, resolve=True)
