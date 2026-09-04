"""In-memory Graph API transport for tests. Nothing here reaches Facebook."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse


class FakeTransport:
    """Maps ``METHOD path`` to a ``(status, payload)`` pair.

    The path is the Graph API path after the version, for example ``/me/accounts``.
    Query strings are ignored when matching so tokens never appear in the key.
    """

    def __init__(self, responses: dict[str, tuple[int, dict]] | None = None):
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(
        self,
        method: str,
        url: str,
        data: bytes | None,
        headers: dict[str, str],
        timeout: int,
    ) -> tuple[int, bytes]:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0].startswith("v") and len(parts[0]) > 1 and parts[0][1].isdigit():
            parts = parts[1:]
        path = "/" + "/".join(parts) if parts else "/"

        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        body: dict[str, str] = {}
        if data:
            body = {key: values[-1] for key, values in parse_qs(data.decode("utf-8")).items()}

        # Tokens must never be asserted by value in caller tests; record only
        # that they were present.
        recorded = {**query, **body}
        self.calls.append((method, path, recorded))

        key = f"{method} {path}"
        if key not in self.responses:
            raise AssertionError(f"Unexpected Graph API call: {key}")
        status, payload = self.responses[key]
        return status, json.dumps(payload).encode("utf-8")
