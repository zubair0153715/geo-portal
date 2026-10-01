"""Fernet-encrypted credential vault.

All third-party secrets (OAuth refresh tokens, AI API keys, WordPress
application passwords) are stored encrypted in the `connections` table.
The master key comes ONLY from the GEO_VAULT_KEY environment variable.

Secrets are never logged: decrypt results are never passed to print()/logging.

Generate a key with:
    python -m app.vault genkey
"""

import json
import os
import sys

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    key = os.environ.get("GEO_VAULT_KEY")
    if not key:
        raise RuntimeError(
            "GEO_VAULT_KEY is not set. Generate one with "
            "'python -m app.vault genkey' and put it in your .env file."
        )
    return Fernet(key.strip().encode())


def encrypt_dict(payload: dict) -> str:
    """Encrypt a JSON-serialisable dict -> opaque string for DB storage."""
    raw = json.dumps(payload).encode("utf-8")
    return _fernet().encrypt(raw).decode("utf-8")


def decrypt_dict(blob: str) -> dict:
    """Decrypt a vault blob back to a dict. Raises on wrong key / tampering."""
    raw = _fernet().decrypt(blob.strip().encode("utf-8"))
    return json.loads(raw.decode("utf-8"))


def generate_key() -> str:
    return Fernet.generate_key().decode("utf-8")


if __name__ == "__main__":
    # CLI helper:  python -m app.vault genkey
    if len(sys.argv) == 2 and sys.argv[1] == "genkey":
        print(generate_key())
    else:
        print("usage: python -m app.vault genkey")
        sys.exit(2)
