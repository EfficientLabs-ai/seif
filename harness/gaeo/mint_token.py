#!/usr/bin/env python3
"""Mint a short-lived GitHub App installation token from the VAULTED private key.

The private key is read from ~/.config/seif/seif-bot.pem at runtime and is NEVER
printed or logged. Installation tokens expire in ~1h. This is the only bridge between
the seif-bot App identity and git/gh operations — agents call this, they never hold the key.

Usage:
  python3 mint_token.py installations          # list installations (verify the key works — no secret printed)
  python3 mint_token.py token <installation_id> # print a short-lived installation token (SECRET — pipe, don't log)
Requires: pyjwt, cryptography  (pip install --user pyjwt cryptography)
"""
import sys
import time
import json
import urllib.request
from pathlib import Path

KEY = Path.home() / ".config" / "seif" / "seif-bot.pem"
APP_ID = "4101951"
INSTALLATION_ID = "141520088"  # EfficientLabs-ai (verified 2026-06-20: seif-bot authenticates)
API = "https://api.github.com"


def _jwt():
    import jwt  # PyJWT
    now = int(time.time())
    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": APP_ID}, KEY.read_text(), algorithm="RS256")


def _api(method, path, bearer, data=None):
    req = urllib.request.Request(
        API + path, method=method, data=json.dumps(data).encode() if data else None,
        headers={"Authorization": f"Bearer {bearer}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "seif-bot"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    if not KEY.exists():
        sys.exit(f"private key not found at {KEY} — vault it first (it is never read into chat)")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "installations"
    jwt_tok = _jwt()
    if cmd == "installations":
        for i in _api("GET", "/app/installations", jwt_tok):
            print(f"installation_id={i['id']} account={i['account']['login']} selection={i.get('repository_selection')}")
    elif cmd == "token":
        inst = sys.argv[2] if len(sys.argv) > 2 else INSTALLATION_ID
        out = _api("POST", f"/app/installations/{inst}/access_tokens", jwt_tok)
        print(out["token"])  # short-lived SECRET — pipe into git, do not echo to logs
    else:
        sys.exit("usage: mint_token.py installations | token <installation_id>")


if __name__ == "__main__":
    main()
