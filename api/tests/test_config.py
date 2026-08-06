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
