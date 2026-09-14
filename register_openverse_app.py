"""
One-time setup helper — NOT part of the daily bots.

Registers this project as an application with the Openverse API and
prints back a client_id / client_secret. Run this exactly once (via the
"Register Openverse App (one-time setup)" workflow), copy the two
printed values into this repo's secrets, and you're done — the bots
will pick them up automatically as OPENVERSE_CLIENT_ID /
OPENVERSE_CLIENT_SECRET.

Why this exists: anonymous (unauthenticated) requests to Openverse have
been unreliable for this project — rate-limited or filtered outright —
which is why reels were coming out with no background music. An
authenticated application gets a much higher, stable rate limit.

Usage (normally triggered by the workflow, not run by hand):
    OPENVERSE_CONTACT_EMAIL=you@example.com python register_openverse_app.py
"""

import os
import sys

import requests

OPENVERSE_BASE = "https://api.openverse.org/v1"


def main():
    email = os.environ.get("OPENVERSE_CONTACT_EMAIL", "").strip()
    if not email:
        print("[error] OPENVERSE_CONTACT_EMAIL was not set — re-run the workflow "
              "and fill in the email input.")
        sys.exit(1)

    resp = requests.post(
        f"{OPENVERSE_BASE}/auth_tokens/register/",
        json={
            "name": "igauto-bot",
            "description": "Instagram nature-quote reel bot — background music fetcher",
            "email": email,
        },
        headers={"User-Agent": "igauto-bot/1.0 (instagram nature-quote reel bot)"},
        timeout=15,
    )
    if not resp.ok:
        print(f"[error] Registration failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    data = resp.json()
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")

    print("\n" + "=" * 70)
    print("Registered! Copy these into: Settings -> Secrets and variables")
    print("-> Actions -> New repository secret (add TWO separate secrets):")
    print("=" * 70)
    print(f"  Name:  OPENVERSE_CLIENT_ID\n  Value: {client_id}\n")
    print(f"  Name:  OPENVERSE_CLIENT_SECRET\n  Value: {client_secret}\n")
    print("=" * 70)
    print("Once both secrets are saved, the daily bots will start")
    print("authenticating automatically — no other changes needed.")
    print("You can ignore/delete this script and its workflow after this.")


if __name__ == "__main__":
    main()
