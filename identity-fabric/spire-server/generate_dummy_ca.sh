#!/bin/bash
# Generate dummy upstream CA for MVP - NOT FOR PRODUCTION USE

openssl req -x509 -newkey rsa:2048 -days 365 -keyout dummy_upstream_ca.key -out dummy_upstream_ca.crt -nodes \
  -subj "/C=US/ST=CA/L=San Francisco/O=AgentVault/OU=Identity/CN=AgentVault Dummy CA"
