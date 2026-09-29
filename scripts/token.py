#!/usr/bin/env python3
"""Mint a short-lived HS256 JWT that Kong's jwt plugin accepts for /billing/*.

    export TOKEN=$(python3 scripts/token.py)
    curl localhost:8000/billing/consumers -H "Authorization: Bearer $TOKEN"

Uses JWT_SECRET from the environment (same default as docker-compose.yml).
"""
import base64
import hashlib
import hmac
import json
import os
import time


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


secret = os.getenv("JWT_SECRET", "dev-secret-change-me-please-32b!")
ttl = int(os.getenv("TTL_SECONDS", "3600"))
head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
body = b64(json.dumps({"iss": "dashboard", "exp": int(time.time()) + ttl}).encode())
sig = b64(hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
print(f"{head}.{body}.{sig}")
