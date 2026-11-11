"""Fake smart meters for the DYNAMO recipe: each meter publishes its readings (QoS 1) to meters/<meter>/reading on an
MQTT broker, with its own sequence number. Needs paho-mqtt (the proxy-mqtt extra); a mosquitto container serves as
the broker in the sandbox drive.

    python fake_meters.py --host 127.0.0.1 --port 1883 --meters 3 --readings 4
"""
import argparse
import datetime as dt
import json


def readings(meters: int, count: int, start: int = 1):
    """(topic, body) for each reading, meter by meter."""
    for m in range(meters):
        meter = f"MTR-{m + 1:04d}"
        for r in range(start, start + count):
            yield f"meters/{meter}/reading", {
                "seq": f"{meter}-{r:06d}", "kwh": round(1200.5 + 3.25 * r + m, 3), "voltage": 230 + m,
                "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--meters", type=int, default=3)
    ap.add_argument("--readings", type=int, default=4)
    ap.add_argument("--start", type=int, default=1, help="the first reading number (a later run continues)")
    a = ap.parse_args()
    import paho.mqtt.client as mqtt     # the proxy-mqtt extra
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fake-meters")
    c.connect(a.host, a.port)
    c.loop_start()
    for topic, body in readings(a.meters, a.readings, a.start):
        info = c.publish(topic, json.dumps(body), qos=1)
        info.wait_for_publish(10)
        print(topic, body["seq"], body["kwh"])
    c.loop_stop()
    c.disconnect()


if __name__ == "__main__":
    main()
