"""§SOVKIT-2 R1 (2026-09-14): how the store's Kafka clients authenticate to the broker and verify it.

Measured before: every frame's Redpanda took plaintext connections from anything on the frame network and no client passed a
security setting at all. The broker's side (SCRAM users, ACLs, a TLS listener with the frame's SPIRE-issued certificate) is the
frame kit's; this module is the store's side, read from env so a frame, or an operator running a managed cluster, configures it
without code:

  KAFKA_SECURITY_PROTOCOL   PLAINTEXT (default) | SSL | SASL_PLAINTEXT | SASL_SSL
  KAFKA_SASL_MECHANISM      SCRAM-SHA-256 (default) | SCRAM-SHA-512   (PLAIN is refused: it sends the password as written)
  KAFKA_SASL_USERNAME / KAFKA_SASL_PASSWORD
  KAFKA_SSL_CAFILE          the CA the broker's certificate must chain to (the frame's SPIRE bundle); hostname verified
  KAFKA_SSL_CERTFILE / KAFKA_SSL_KEYFILE   optional: present a client certificate to a broker that asks for one

A setting that cannot work refuses loudly at client construction instead of connecting in a weaker mode.
"""
import os
import ssl

PROTOCOLS = ("PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL")
MECHANISMS = ("SCRAM-SHA-256", "SCRAM-SHA-512")


def _protocol() -> str:
    return (os.getenv("KAFKA_SECURITY_PROTOCOL") or "PLAINTEXT").strip().upper()


def _mechanism() -> str:
    return (os.getenv("KAFKA_SASL_MECHANISM") or "SCRAM-SHA-256").strip().upper()


def client_security_kwargs() -> dict:
    """Keyword arguments for AIOKafkaProducer / AIOKafkaConsumer. Empty for PLAINTEXT, so today's frames are unchanged."""
    protocol = _protocol()
    if protocol not in PROTOCOLS:
        raise ValueError(f"KAFKA_SECURITY_PROTOCOL={protocol!r} is not one of {', '.join(PROTOCOLS)}")
    if protocol == "PLAINTEXT":
        return {}
    kwargs = {"security_protocol": protocol}
    if protocol.endswith("SSL"):
        context = ssl.create_default_context(cafile=os.getenv("KAFKA_SSL_CAFILE") or None)
        certfile = os.getenv("KAFKA_SSL_CERTFILE") or None
        if certfile:
            context.load_cert_chain(certfile, os.getenv("KAFKA_SSL_KEYFILE") or None)
        kwargs["ssl_context"] = context
    if protocol.startswith("SASL_"):
        mechanism = _mechanism()
        if mechanism not in MECHANISMS:
            raise ValueError(f"KAFKA_SASL_MECHANISM={mechanism!r} is not one of {', '.join(MECHANISMS)}")
        user, password = os.getenv("KAFKA_SASL_USERNAME", ""), os.getenv("KAFKA_SASL_PASSWORD", "")
        if not user or not password:
            raise ValueError(f"KAFKA_SECURITY_PROTOCOL={protocol} needs KAFKA_SASL_USERNAME and KAFKA_SASL_PASSWORD")
        kwargs.update(sasl_mechanism=mechanism, sasl_plain_username=user, sasl_plain_password=password)
    return kwargs


def describe() -> dict:
    """The posture for /health: names and booleans, never a credential."""
    protocol = _protocol()
    out = {"protocol": protocol}
    if protocol.startswith("SASL_"):
        out["sasl_mechanism"] = _mechanism()
        out["sasl_user_set"] = bool(os.getenv("KAFKA_SASL_USERNAME"))
    if protocol.endswith("SSL"):
        out["ca_file_set"] = bool(os.getenv("KAFKA_SSL_CAFILE"))
        out["client_cert_set"] = bool(os.getenv("KAFKA_SSL_CERTFILE"))
    return out
