#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# The broker tests/test_proxy_source_mqtt_broker.py runs against: eclipse-mosquitto 2 in a container of its own. The
# tests write its configuration, certificates and password file into the directory shared at /ctl (at test time, so no
# key is ever kept in the repository), and restart it when they create /ctl/restart; its persistence lives in the
# container (/mosquitto/data), so a restart keeps the sessions, as a broker's restart in a plant does.
#
#   docker network create codek-mqtt
#   docker run -d --name codek-mosquitto --network codek-mqtt -v "$CTL":/ctl \
#     -v "$PWD/tests/mqtt_broker.sh":/broker.sh:ro --entrypoint /bin/sh eclipse-mosquitto:2 /broker.sh
#
# /ctl/up holds the number of the broker's current start (written once it runs); /ctl/broker.log is its log.
set -u
n=0
while :; do
  while [ ! -e /ctl/mosquitto.conf ]; do sleep 0.2; done
  rm -f /ctl/restart
  if [ -e /ctl/passwd.plain ]; then
    cp /ctl/passwd.plain /tmp/passwd && mosquitto_passwd -U /tmp/passwd
  fi
  mosquitto -c /ctl/mosquitto.conf >> /ctl/broker.log 2>&1 &
  pid=$!
  n=$((n + 1))
  echo "$n" > /ctl/up.tmp && mv /ctl/up.tmp /ctl/up
  while kill -0 "$pid" 2>/dev/null; do
    if [ -e /ctl/restart ]; then
      rm -f /ctl/up
      kill -TERM "$pid"
      wait "$pid"
      break
    fi
    sleep 0.1
  done
  rm -f /ctl/up
  sleep 0.5
done
