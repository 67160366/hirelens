"""Settings guards.

The one that matters: a deploy that forgets JWT_SECRET must die at startup
rather than sign every token with a secret committed to the repository.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import DEFAULT_JWT_SECRET, AppEnv, Settings


class TestJwtSecretGuard:
    def test_prod_refuses_the_placeholder_secret(self):
        with pytest.raises(ValidationError, match="JWT_SECRET"):
            Settings(app_env=AppEnv.PROD, jwt_secret=DEFAULT_JWT_SECRET)

    def test_prod_accepts_a_real_secret(self):
        settings = Settings(app_env=AppEnv.PROD, jwt_secret="x" * 48)
        assert settings.app_env is AppEnv.PROD

    def test_dev_accepts_the_placeholder(self):
        settings = Settings(app_env=AppEnv.DEV, jwt_secret=DEFAULT_JWT_SECRET)
        assert settings.jwt_secret == DEFAULT_JWT_SECRET


class TestCorsOrigins:
    """The dev server does not always get port 3000, and a CORS rejection names
    nothing useful — so the allowlist has to be reachable from the environment."""

    def test_the_default_covers_the_dev_server(self):
        assert "http://localhost:3000" in Settings(_env_file=None).cors_origins

    def test_a_comma_separated_value_is_split(self):
        """The natural way to write it in a shell. Plain JSON would be the only
        alternative, and nobody types that into a .env by choice."""
        settings = Settings(
            _env_file=None, cors_origins="http://localhost:3002, http://127.0.0.1:3002"
        )
        assert settings.cors_origins == ["http://localhost:3002", "http://127.0.0.1:3002"]

    def test_a_real_list_still_works(self):
        settings = Settings(_env_file=None, cors_origins=["http://example.test"])
        assert settings.cors_origins == ["http://example.test"]
