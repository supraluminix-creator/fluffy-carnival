#!/usr/bin/env python3
"""Fetch large Ethereum transactions (whale alerts) via Etherscan."""

from __future__ import annotations

import asyncio

from integrations.etherscan_adapter import load_config, refresh


def main() -> int:
    cfg = load_config()
    path = asyncio.run(refresh(cfg))
    if path:
        print(f"Etherscan whale events exported to {path}")
        return 0
    print("Etherscan collector skipped (disabled or misconfigured)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
