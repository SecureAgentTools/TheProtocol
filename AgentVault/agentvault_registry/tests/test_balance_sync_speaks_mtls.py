"""§BALTLS (2026-09-10) — THE BALANCE CACHE'S RE-READ HAD NO IDENTITY, SO IT NEVER ARRIVED.

§FRAMELIC row 164 taught this worker to subscribe to `LedgerBalanceChanged`, the event EVERY
balance movement produces. It was the right subscription and it changed nothing on three of five
frames, because the re-read it triggers opened a bare `aiohttp.ClientSession()` — system CA store,
no client certificate — against a TEG that sits behind an mTLS sidecar:

    registry-a        TEG_API_BASE_URL=https://nginx-teg-a:8443        562 failures / hour
    frame-b-registry  TEG_API_BASE_URL=https://frame-b-nginx-teg:8443  562 failures / hour
    frame-c-registry  TEG_API_BASE_URL=https://frame-c-nginx-teg:8443  562 failures / hour
    eu-registry       TEG_API_BASE_URL=http://eu-teg:8080                0
    asia-registry     TEG_API_BASE_URL=http://asia-teg:8080              0

Every one of them `CERTIFICATE_VERIFY_FAILED`, counted as `teg_error`, logged, cache left stale —
the handler doing exactly what it was written to do while the transport underneath it could not
complete a handshake. The two frames with a plain-http TEG were the control all along, and the
cache census says the same thing from the other side (measured 2026-09-10, registry DB against
TEG DB, no HTTP):

    Frame-A   184 agents drifted   31,639,199.44 divergence
    Frame-B   149 agents drifted   22,097,121.50
    Frame-C   517 agents drifted   21,936,226.02
    EU          0                           0.00
    ASIA        0                           0.00

`get_es_ssl_context()` is the context this fleet ALREADY uses for internal mTLS — the same one
`get_httpx_verify()` hands a dozen routers. It trusts the SPIRE bundle and the public roots,
presents `/certs/svid.0.pem`, and rebuilds itself when cert-writer rotates the SVID. Hand-rolling
a second one here is the money-helper-with-its-own-transport shape
([[feedback_handrolled_transport_bypasses_shared_client_hardening]]).

Proven both ways on all five live registries BEFORE this was written:
registry-a / frame-b / frame-c went CERTIFICATE_VERIFY_FAILED -> 200, EU / ASIA stayed 200 -> 200.
"""
import asyncio
import os
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DID = "did:theprotocol:eu.theprotocol.cloud:8fad1ffd-383d-4e3d-820f-9a83031ea806"


def _run(coro):
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Resp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    """Records the kwargs the worker hands its request — the whole question is whether `ssl` is
    among them."""

    def __init__(self, calls, status, payload):
        self.calls = calls
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Resp(self.status, self.payload)


def _drive(teg_url, *, ctx=object(), status=200, payload=None):
    """Run the real `_sync_agent_from_teg` with the transport and the DB spied."""
    from agentvault_registry.background_tasks import eventstore_balance_sync as m

    calls, db_opened, counted = [], [], []

    class _AioShim:
        ClientTimeout = m.aiohttp.ClientTimeout

        @staticmethod
        def ClientSession(*a, **kw):
            return _Session(calls, status, payload if payload is not None
                            else {"agent_id": DID, "teg_initialized": True, "balance": "12.5"})

    class _DbCtx:
        async def __aenter__(self):
            db_opened.append(True)
            raise AssertionError("the DB must not be opened for this case")

        async def __aexit__(self, *a):
            return False

    # `get_es_ssl_context` is PART of the fix, so it is patched only when it is there. That keeps
    # the two "nothing changed" cases below runnable against the PRE-FIX module, which is the only
    # way they can honestly claim to be controls.
    _MISSING = object()
    saved = (m.aiohttp, getattr(m, "get_es_ssl_context", _MISSING), m.get_db_context, m._count,
             os.environ.get("TEG_API_BASE_URL"))
    m.aiohttp = _AioShim
    if saved[1] is not _MISSING:
        m.get_es_ssl_context = lambda: ctx
    m.get_db_context = lambda: _DbCtx()
    m._count = lambda outcome: counted.append(outcome)
    os.environ["TEG_API_BASE_URL"] = teg_url
    try:
        _run(m._sync_agent_from_teg(DID))
    finally:
        m.aiohttp, m.get_db_context, m._count = saved[0], saved[2], saved[3]
        if saved[1] is _MISSING:
            if hasattr(m, "get_es_ssl_context"):
                del m.get_es_ssl_context
        else:
            m.get_es_ssl_context = saved[1]
        if saved[4] is None:
            os.environ.pop("TEG_API_BASE_URL", None)
        else:
            os.environ["TEG_API_BASE_URL"] = saved[4]
    return calls, counted, db_opened


# --------------------------------------------------------------------------------------------
def test_an_https_teg_is_dialled_with_the_shared_svid_context():
    """The fix. Before it, `ssl` was in no request and the handshake could not complete."""
    sentinel = object()
    calls, _, _ = _drive("https://frame-b-nginx-teg:8443", ctx=sentinel)
    assert len(calls) == 1, calls
    url, kwargs = calls[0]
    assert kwargs.get("ssl") is sentinel, kwargs
    assert url.startswith("https://frame-b-nginx-teg:8443/api/v1/agent/"), url


def test_a_plain_http_teg_is_dialled_exactly_as_before():
    """CONTROL — EU and ASIA work today and must be byte-identical after the change. An `ssl`
    argument on a plain-http request would be new behaviour on the only two frames that were
    never broken."""
    calls, _, _ = _drive("http://eu-teg:8080", ctx=object())
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert "ssl" not in kwargs, kwargs
    assert "headers" in kwargs and "timeout" in kwargs, kwargs


def test_a_node_with_no_svid_on_disk_still_calls():
    """`get_es_ssl_context()` returns None where `/certs` does not exist. That must degrade to
    today's behaviour, never to a crash — a worker that raises is a worker that stops."""
    calls, counted, _ = _drive("https://nginx-teg-a:8443", ctx=None)
    assert len(calls) == 1
    assert "ssl" not in calls[0][1], calls[0][1]


def test_no_teg_account_is_not_a_zero_balance():
    """`GET /agent/{id}/teg-status` answers **200** with `teg_initialized: false` and NO `balance`
    key when the profile is missing. `.get("balance", 0)` turned that into a zero and would have
    written it over the cache — the `.get()`-on-a-missing-key class deciding a WRITE.

    Censused 2026-09-10: 3,613 registry rows across the five live frames have no TEG profile and
    every one already caches 0, so the bad write never had anything to destroy — and this path
    only began executing at all with the transport fix above."""
    calls, counted, db_opened = _drive(
        "https://nginx-teg-a:8443",
        payload={"agent_id": DID, "teg_initialized": False,
                 "message": "Agent does not have a TEG account"})
    assert len(calls) == 1
    assert counted == ["not_found"], counted
    assert db_opened == [], "an uninitialised account must not reach the cache write"


def test_a_balance_of_zero_is_still_a_balance():
    """The other side of the same coin: a real zero must NOT be mistaken for a missing account."""
    from agentvault_registry.background_tasks import eventstore_balance_sync as m

    calls, counted, db_opened = _drive(
        "https://nginx-teg-a:8443",
        payload={"agent_id": DID, "teg_initialized": True, "balance": "0"})
    assert len(calls) == 1
    assert True in db_opened, "a real zero must go on to the cache comparison"
    assert "not_found" not in counted, counted


def test_the_shared_helper_is_the_one_used():
    """A second hand-rolled SSL context here would drift from the fleet's and would not follow a
    cert-writer rotation. Pin the import, not merely the behaviour."""
    src = (SRC / "agentvault_registry" / "background_tasks"
           / "eventstore_balance_sync.py").read_text()
    assert "from ..es_ssl_helper import get_es_ssl_context" in src
    assert "ssl.create_default_context" not in src, "do not build a second context here"
    assert "verify=False" not in src and "ssl=False" not in src, "never disable verification"
