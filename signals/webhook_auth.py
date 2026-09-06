# signals/webhook_auth.py
"""Zero trust authentication for webhooks."""

from __future__ import annotations

import ipaddress
import os
from fastapi import HTTPException

ALLOWED_IPS = [ipaddress.ip_network(ip.strip()) for ip in os.getenv("WEBHOOK_ALLOWED_IPS", "127.0.0.1").split(",") if ip.strip()]
GEO_BLOCK = os.getenv("WEBHOOK_GEO_BLOCK", "").split(",")

def validate_ip_trust(ip: str) -> None:
    """Validate IP against allowlist."""
    client_ip = ipaddress.ip_address(ip)
    if not any(client_ip in net for net in ALLOWED_IPS):
        raise HTTPException(status_code=403, detail="IP not allowed")

    # Placeholder for geo-blocking
    # if country in GEO_BLOCK: raise

__all__ = ["validate_ip_trust"]