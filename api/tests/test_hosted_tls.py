"""Custom database CAs extend trust while preserving certificate validation."""

import ssl
from pathlib import Path

import pytest

from app.config import Settings
from app.db import database_connect_args


def test_custom_ca_preserves_system_trust_and_hostname_validation():
    ca = Path(__file__).resolve().parents[1] / "certs/supabase-prod-ca-2021.crt"
    context = database_connect_args(
        Settings(
            _env_file=None,
            database_ssl=True,
            database_ssl_ca_file=str(ca),
        )
    )["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    default_anchors = set(ssl.create_default_context().get_ca_certs(binary_form=True))
    assert default_anchors <= set(context.get_ca_certs(binary_form=True))
    assert any(
        ("commonName", "Supabase Root 2021 CA") in entry
        for certificate in context.get_ca_certs()
        for entry in certificate["subject"]
    )


def test_ca_without_tls_is_refused():
    with pytest.raises(ValueError, match="DATABASE_SSL_CA_FILE requires"):
        database_connect_args(Settings(_env_file=None, database_ssl_ca_file="missing.pem"))


def test_missing_ca_fails_instead_of_disabling_validation(tmp_path):
    with pytest.raises(FileNotFoundError):
        database_connect_args(
            Settings(
                _env_file=None,
                database_ssl=True,
                database_ssl_ca_file=str(tmp_path / "missing.pem"),
            )
        )
