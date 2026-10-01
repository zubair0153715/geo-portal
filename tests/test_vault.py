"""Vault: Fernet encrypt/decrypt round-trip, wrong-key failure, no plaintext leak."""

import os

import pytest

from app import vault


@pytest.fixture()
def key(monkeypatch):
    k = vault.generate_key()
    monkeypatch.setenv("GEO_VAULT_KEY", k)
    return k


def test_round_trip(key):
    payload = {"api_key": "sk-test-123", "nested": {"a": 1}}
    blob = vault.encrypt_dict(payload)
    assert vault.decrypt_dict(blob) == payload


def test_blob_does_not_contain_plaintext(key):
    blob = vault.encrypt_dict({"api_key": "sk-super-secret-xyz"})
    assert "sk-super-secret-xyz" not in blob


def test_wrong_key_fails(key, monkeypatch):
    blob = vault.encrypt_dict({"api_key": "abc"})
    monkeypatch.setenv("GEO_VAULT_KEY", vault.generate_key())  # different key
    with pytest.raises(Exception):
        vault.decrypt_dict(blob)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEO_VAULT_KEY", raising=False)
    with pytest.raises(RuntimeError):
        vault.encrypt_dict({"a": 1})


def test_tampered_blob_fails(key):
    blob = vault.encrypt_dict({"a": 1})
    tampered = blob[:-4] + ("A" if not blob.endswith("A") else "B")
    with pytest.raises(Exception):
        vault.decrypt_dict(tampered)
