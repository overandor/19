"""The remote front end: run the model on the host, not on the laptop.

The client-side memory win is the blunt one — work that runs on the shell
host does not occupy the client's RAM at all — and it only counts if the
front end does not become the weak point. So this deliberately does *not*
implement SSH.

Hand-rolled transport crypto is how this kind of component gets broken.
Instead the service speaks a line-delimited JSON protocol over stdin and
stdout, and OpenSSH runs it: `sshd` authenticates the key, then invokes
this as a forced command. Authentication, key management, transport
encryption, rekeying and the rest stay with the implementation that has
been attacked for twenty-five years. See `docs/MEMORY_SHELL.md` for the
`authorized_keys` line.

The security property that matters most here is one line of code and easy
to get wrong: **the tenant comes from the server-side `authorized_keys`
entry, never from the request.** A client that puts `"tenant": "alice"` in
its payload is ignored. Identity is a property of the key that
authenticated, and a protocol that lets the caller name itself has no
isolation at all, however careful the cache underneath is.

The rest is ordinary hardening: an allow-list of three operations, a frame
size cap, no subprocess anywhere, no filesystem surface, and errors that
do not distinguish "forbidden" from "absent" — matching the guarantee
`isolation.py` makes, so the protocol does not reopen the channel the
store closed.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO

from .isolation import Tenant
from .shell import MemoryShell

MAX_FRAME_BYTES = 8 * 1024 * 1024
TENANT_ENV_VAR = "MEMORY_SHELL_TENANT"
SHARED_SCOPES_ENV_VAR = "MEMORY_SHELL_SHARED_SCOPES"

ALLOWED_OPS = frozenset({"run", "stat", "ping"})

# (work_class, input payload) -> output bytes. Supplied by the operator; in
# a real deployment this is the model. There is deliberately no default
# that executes anything the client supplies.
Computer = Callable[[str, bytes], bytes]


class ProtocolError(Exception):
    pass


def tenant_from_environment() -> Tenant:
    """Identity from the environment sshd set, not from the client.

    `authorized_keys` can pin per-key environment with
    `environment="MEMORY_SHELL_TENANT=alice"`, which the client cannot
    influence. Absent that, there is no identity and the service refuses
    to start rather than defaulting to a shared one.
    """
    tenant_id = os.environ.get(TENANT_ENV_VAR, "").strip()
    if not tenant_id:
        raise ProtocolError(
            f"{TENANT_ENV_VAR} is unset. The tenant must come from the "
            "authorized_keys entry that authenticated this connection; "
            "refusing to serve an unidentified session."
        )
    raw_scopes = os.environ.get(SHARED_SCOPES_ENV_VAR, "")
    scopes = frozenset(s.strip() for s in raw_scopes.split(",") if s.strip())
    return Tenant(tenant_id=tenant_id, shared_scopes=scopes)


@dataclass
class RemoteShellService:
    """One authenticated connection's view of the shell."""

    shell: MemoryShell
    tenant: Tenant
    compute: Computer

    def handle(self, frame: bytes) -> bytes:
        """Process one request frame, returning one response frame."""
        if len(frame) > MAX_FRAME_BYTES:
            return self._error(
                f"frame exceeds {MAX_FRAME_BYTES} bytes", code="too_large"
            )
        try:
            request = json.loads(frame)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._error("malformed frame", code="bad_request")
        if not isinstance(request, dict):
            return self._error("frame must be an object", code="bad_request")

        op = request.get("op")
        if op not in ALLOWED_OPS:
            # Do not echo the requested op back; it is attacker-controlled
            # and would land in whatever reads these logs.
            return self._error("unsupported operation", code="bad_request")

        handler = getattr(self, f"_op_{op}")
        try:
            return handler(request)
        except ProtocolError as exc:
            return self._error(str(exc), code="bad_request")

    # ── operations ─────────────────────────────────────────────────────

    def _op_ping(self, request: dict) -> bytes:
        return self._ok({"tenant": self.tenant.tenant_id})

    def _op_stat(self, request: dict) -> bytes:
        stats = self.shell.stats()
        acc = stats.accounting
        return self._ok(
            {
                "resident_bytes": acc.resident_bytes,
                "logical_bytes": acc.logical_bytes,
                "saved_bytes": acc.saved_bytes,
                "dedup_ratio": round(acc.dedup_ratio, 4),
                "hit_rate": round(acc.hit_rate, 4),
                "weights_resident_bytes": stats.weights_resident_bytes,
                "weights_saved_bytes": stats.weights_saved_bytes,
                "rss_bytes": stats.rss_bytes,
            }
        )

    def _op_run(self, request: dict) -> bytes:
        work_class = request.get("work_class")
        if not isinstance(work_class, str) or not work_class:
            raise ProtocolError("work_class must be a non-empty string")

        payload = _decode_payload(request.get("payload"))
        hold = bool(request.get("hold", False))
        shareable = bool(request.get("shareable", False))
        shared_label = request.get("shared_label")
        if shared_label is not None and not isinstance(shared_label, str):
            raise ProtocolError("shared_label must be a string")

        # Note what is NOT read from the request: the tenant. Identity comes
        # from the authenticated connection, so a client cannot address
        # another tenant's cache by asking to.
        with self.shell.session(self.tenant) as session:
            result = session.run(
                work_class,
                payload,
                lambda: self.compute(work_class, payload),
                shareable=shareable,
                shared_label=shared_label,
                hold=hold,
            )

        return self._ok(
            {
                "output": base64.b64encode(result.output).decode("ascii"),
                "reused": result.reused,
                "cost_seconds": round(result.cost_seconds, 9),
                "saved_seconds": round(result.saved_seconds, 9),
                "nbytes": result.nbytes,
            }
        )

    # ── framing ────────────────────────────────────────────────────────

    def _ok(self, body: dict) -> bytes:
        return json.dumps({"ok": True, **body}, separators=(",", ":")).encode()

    def _error(self, message: str, code: str) -> bytes:
        return json.dumps(
            {"ok": False, "code": code, "error": message}, separators=(",", ":")
        ).encode()


def _decode_payload(raw: object) -> bytes:
    if not isinstance(raw, str):
        raise ProtocolError("payload must be a base64 string")
    if len(raw) > MAX_FRAME_BYTES:
        raise ProtocolError("payload too large")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError("payload is not valid base64") from exc


def serve(
    service: RemoteShellService,
    stdin: BinaryIO,
    stdout: BinaryIO,
    max_requests: int | None = None,
) -> int:
    """Read request frames from stdin, write response frames to stdout.

    One JSON object per line in each direction. Runs until EOF, which is
    what sshd delivers when the client disconnects.
    """
    served = 0
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        response = service.handle(line)
        stdout.write(response + b"\n")
        stdout.flush()
        served += 1
        if max_requests is not None and served >= max_requests:
            break
    return served
