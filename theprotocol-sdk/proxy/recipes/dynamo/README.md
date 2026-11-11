# DYNAMO: meter readings over MQTT

The DYNAMO blueprint (energy) as a TheProtocol Proxy recipe: `proxy.yaml` here, a fake of the legacy
system in `fake/`, run on the sandbox end to end before it shipped.

**The legacy side.** Smart meters publish JSON readings (`seq`, `kwh`, `voltage`, `at`) to `meters/<meter>/reading` on the plant's broker (QoS 1).

**On TheProtocol.** Each reading becomes a `dynamo.meter_reading` attestation, the meter taken from the topic; a redelivered message is kept once (the meter's `seq` is the id).

**What it needs.** An agent with the `attestor` role; the broker's address, and in production its CA and a client certificate (`tls`). Install the `proxy-mqtt` extra. Credentials come from the agent's starter files (`.env`, `.env.secret`) by reference;
none is written in the spec.

**Try it locally.** `docker run -d -p 1883:1883 eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf` is a broker; `python fake/fake_meters.py --meters 3 --readings 4` publishes twelve readings. Then:

```
tp-proxy validate proxy.yaml
tp-proxy run proxy.yaml --dry-run            # what it would send, sending nothing (Ctrl-C to stop: a receiver never finishes, so --once does not end here)
tp-proxy run proxy.yaml                        # for real
```

**Check it.** `tp-proxy status` shows the readings sent; the attestations are on the agent's record.
