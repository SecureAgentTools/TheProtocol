"""§EXTREACH design A (agentvault2-5b, 2026-10-14): the reachability probe a self-hosted frame asks for.

Offline: the name and port rules, the address guard (no private address, never this server), the verdicts, and real
dials against TLS servers on 127.0.0.1 with generated certificates (a lane that names the host, one that does not,
a console certificate no public CA signed, a closed port, a bundle endpoint and a page that is not one).
"""
import asyncio
import datetime
import json
import ssl
import tempfile

import pytest

from agentvault_registry.routers import public_reach_probe as rp


def test_names():
    assert rp.normalize_name(" Frame.Example.ORG. ") == "frame.example.org"
    for bad in ("localhost", "203.0.113.5", "::1", "-x.example.org", "a..b", "x" * 300 + ".org", "frame_x.org", ""):
        with pytest.raises(ValueError):
            rp.normalize_name(bad)


def test_ports():
    assert rp.plan_ports({}) == [("console", 443), ("federation", 8443), ("bundle", 8444), ("ledger", 8445)]
    assert dict(rp.plan_ports({"bundle": 8454}))["bundle"] == 8454
    for bad in ({"ssh": 22}, {"bundle": 0}, {"bundle": 70000}, {"bundle": "8444"}, {"bundle": True},
                {"bundle": 8443}):
        with pytest.raises(ValueError):
            rp.plan_ports(bad)


def test_the_address_guard():
    assert rp.choose_address([], set()) == (None, "no_address")
    for private in ("10.0.0.5", "172.16.1.1", "192.168.1.2", "127.0.0.1", "169.254.1.1", "100.64.0.9", "0.0.0.0"):
        assert rp.choose_address([private], set()) == (None, "private_address"), private
    assert rp.choose_address(["198.51.100.7", "10.0.0.5"], set())[1] == "private_address", "every address counts"
    assert rp.choose_address(["1.2.3.4"], {"1.2.3.4"}) == (None, "this_server")
    assert rp.choose_address(["8.8.8.8"], {"1.2.3.4"}) == ("8.8.8.8", None)


def test_this_server_is_denied_from_its_public_url(monkeypatch):
    monkeypatch.setenv("REACH_PROBE_DENY_ADDRESSES", "198.51.100.9, 198.51.100.10")
    monkeypatch.setenv("PUBLIC_URL", "https://localhost")
    deny = rp.deny_addresses()
    assert {"198.51.100.9", "198.51.100.10", "127.0.0.1"} <= deny


def test_the_flag_is_positive(monkeypatch):
    monkeypatch.delenv("REACH_PROBE_ENABLED", raising=False)
    assert not rp.enabled()
    monkeypatch.setenv("REACH_PROBE_ENABLED", "true")
    assert rp.enabled()


def test_verdicts():
    assert rp.verdict_of(asyncio.TimeoutError())[0] == "timeout"
    assert rp.verdict_of(ConnectionRefusedError())[0] == "refused"
    assert rp.verdict_of(ssl.SSLError())[0] == "not_tls"
    assert rp.verdict_of(OSError("no route"))[0] == "unreachable"


def _cert(dns_names, uri=None):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    names = [x509.DNSName(n) for n in dns_names] + ([x509.UniformResourceIdentifier(uri)] if uri else [])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")]))
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .sign(key, hashes.SHA256()))
    d = tempfile.mkdtemp()
    with open(f"{d}/c.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(f"{d}/k.pem", "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    return f"{d}/c.pem", f"{d}/k.pem"


async def _server(dns_names, uri=None, answer=None):
    cert, key = _cert(dns_names, uri)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(cert, key)

    async def handle(reader, writer):
        try:
            if answer is not None:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(answer)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    srv = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=ctx)
    return srv, srv.sockets[0].getsockname()[1]


@pytest.mark.asyncio
async def test_a_lane_that_names_the_host_is_ok_and_one_that_does_not_is_wrong_name():
    srv, port = await _server(["frame.test"], "spiffe://frame.test/service/frame-nginx-federation")
    async with srv:
        row = await rp.probe_port("127.0.0.1", "frame.test", "federation", port)
    assert row["verdict"] == "ok", row
    assert "spiffe://frame.test/service/frame-nginx-federation" in row["detail"]
    srv, port = await _server(["someone.else"])
    async with srv:
        row = await rp.probe_port("127.0.0.1", "frame.test", "ledger", port)
    assert row["verdict"] == "wrong_name", row


@pytest.mark.asyncio
async def test_a_console_certificate_no_public_ca_signed_is_invalid():
    srv, port = await _server(["frame.test"])
    async with srv:
        row = await rp.probe_port("127.0.0.1", "frame.test", "console", port)
    assert row["verdict"] == "certificate_invalid", row


@pytest.mark.asyncio
async def test_a_closed_port_is_refused():
    srv, port = await _server(["frame.test"])
    srv.close()
    await srv.wait_closed()
    row = await rp.probe_port("127.0.0.1", "frame.test", "ledger", port)
    assert row["verdict"] == "refused", row


@pytest.mark.asyncio
async def test_a_bundle_endpoint_and_a_page_that_is_not_one():
    body = json.dumps({"keys": [{"use": "x509-svid", "kty": "EC", "x5c": ["AAAA"]}]}).encode()
    good = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)
    srv, port = await _server(["frame.test"], answer=good)
    async with srv:
        row = await rp.probe_port("127.0.0.1", "frame.test", "bundle", port)
    assert row["verdict"] == "ok" and "1 x509 root" in row["detail"], row
    page = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 13\r\n\r\n<html></html>"
    srv, port = await _server(["frame.test"], answer=page)
    async with srv:
        row = await rp.probe_port("127.0.0.1", "frame.test", "bundle", port)
    assert row["verdict"] == "not_a_bundle", row
    nope = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
    srv, port = await _server(["frame.test"], answer=nope)
    async with srv:
        row = await rp.probe_port("127.0.0.1", "frame.test", "bundle", port)
    assert row["verdict"] == "not_a_bundle" and "404" in row["detail"], row


def test_chunked_bodies_are_read():
    assert rp._dechunk(b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n") == b"hello world"


# agentvault2-61's review (2026-10-14): a hostile port must not hold a probe open, and strangers must not choose
# ports of a third party's host.

@pytest.mark.asyncio
async def test_a_bundle_port_that_drips_bytes_ends_within_the_read_deadline(monkeypatch):
    monkeypatch.setattr(rp, "CONNECT_TIMEOUT", 2.0)
    monkeypatch.setattr(rp, "READ_TIMEOUT", 1.5)
    cert, key = _cert(["frame.test"])
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(cert, key)
    stop = asyncio.Event()

    async def drip(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{")
            while not stop.is_set():
                await asyncio.sleep(1)
                writer.write(b" ")
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    srv = await asyncio.start_server(drip, "127.0.0.1", 0, ssl=ctx)
    port = srv.sockets[0].getsockname()[1]
    t0 = asyncio.get_running_loop().time()
    async with srv:
        row = await rp.probe_lane("127.0.0.1", "frame.test", "bundle", port)
        stop.set()
    took = asyncio.get_running_loop().time() - t0
    assert took < rp.lane_cap(), took
    assert took < rp.READ_TIMEOUT + rp.CONNECT_TIMEOUT, took
    assert row["verdict"] == "not_a_bundle", row


@pytest.mark.asyncio
async def test_a_lane_that_never_finishes_is_cut_at_the_outer_cap(monkeypatch):
    monkeypatch.setattr(rp, "CONNECT_TIMEOUT", 0.5)
    monkeypatch.setattr(rp, "READ_TIMEOUT", 0.5)

    async def forever(*a, **k):
        await asyncio.sleep(3600)

    monkeypatch.setattr(rp, "probe_port", forever)
    t0 = asyncio.get_running_loop().time()
    row = await rp.probe_lane("127.0.0.1", "frame.test", "ledger", 8445)
    took = asyncio.get_running_loop().time() - t0
    assert row["verdict"] == "timeout" and took < rp.lane_cap() + 1, (row, took)


def test_custom_ports_only_for_a_name_that_points_at_the_caller():
    defaults = rp.plan_ports({})
    moved = rp.plan_ports({"bundle": 8454})
    assert rp.custom_ports_refused(defaults, ["198.51.100.7"], "203.0.113.9") is False, "defaults are for anyone"
    assert rp.custom_ports_refused(moved, ["198.51.100.7"], "198.51.100.7") is False, "the frame asking about itself"
    assert rp.custom_ports_refused(moved, ["198.51.100.7"], "203.0.113.9") is True, "a stranger choosing ports"
    assert rp.custom_ports_refused(moved, ["198.51.100.7"], None) is True


def test_one_global_cap_beside_the_per_caller_one():
    import ast
    import pathlib
    src = pathlib.Path(rp.__file__).read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "reach_probe")
    limits = [d for d in fn.decorator_list if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "limit"]
    assert any(any(k.arg == "key_func" and getattr(k.value, "id", "") == "_everyone" for k in d.keywords) for d in limits)
    assert any(not d.keywords for d in limits), "the per-caller limit stays"
    assert rp._everyone(None) == "reach-probe:global"


def test_the_global_cap_applies_at_runtime(monkeypatch):
    """agentvault2-61's ask (2026-10-14): two stacked @limiter.limit decorators register under one route name, so
    the source alone cannot show both apply. 7 callers x 9 requests: the per-caller 10/hour never trips, so the 61st
    must be refused by the global key; a control endpoint with only the per-caller limit passes all 63."""
    import httpx
    from fastapi import FastAPI, Request
    from agentvault_registry.middleware.rate_limiter import shared_limiter

    monkeypatch.setenv("REACH_PROBE_ENABLED", "true")
    app = FastAPI()
    app.state.limiter = shared_limiter
    app.include_router(rp.router)

    @app.post("/control-without-the-global-cap")
    @shared_limiter.limit("10/hour")
    async def control(request: Request):
        return {"ok": True}

    async def run(path):
        codes = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            for caller in range(7):
                for _ in range(9):
                    r = await c.post(path, json={"public_name": "frame.invalid"},
                                     headers={"X-Forwarded-For": f"198.51.100.{10 + caller}"})
                    codes.append(r.status_code)
        return codes

    shared_limiter.reset()
    try:
        codes = asyncio.run(run("/api/v1/public/reach-probe"))
        assert codes[:60] == [200] * 60, codes[:60]
        assert codes[60:] == [429] * 3, codes[60:]
        control_codes = asyncio.run(run("/control-without-the-global-cap"))
        assert control_codes == [200] * 63, control_codes
    finally:
        shared_limiter.reset()
