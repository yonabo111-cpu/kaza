# -*- coding: utf-8 -*-
"""Application configuration, split by environment.

Selection is driven by the ``KAZA_ENV`` (or ``FLASK_ENV``) environment
variable. Everything the app needs to run — data directory, database URL,
secret key, cookie policy — is resolved here so the rest of the code never
reads ``os.environ`` directly.
"""

from __future__ import annotations

import os
import secrets
from datetime import timedelta

# Repo root = parent of this package directory (…/home-app).
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PACKAGE_DIR)
STATIC_DIR = os.path.join(ROOT_DIR, "static")


def _persistent_secret(data_dir: str) -> str:
    """Return a stable session-signing key, generating and persisting one once.

    Keeping the key on disk means existing logins survive a server restart in
    development. In production ``SECRET_KEY`` should be supplied via the
    environment instead.
    """
    path = os.path.join(data_dir, "secret_key.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(key)
    return key


class BaseConfig:
    """Settings shared by every environment."""

    ENV_NAME = "base"
    DEBUG = False
    TESTING = False

    # Where SQLite and the persisted secret live.
    DATA_DIR = os.environ.get("DATA_DIR", os.path.join(ROOT_DIR, "data"))
    # Empty / "sqlite" → local SQLite file; a postgres URL switches drivers.
    DATABASE_URL = os.environ.get("DATABASE_URL", "")

    # Session cookies: HttpOnly + SameSite=Lax on every environment.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=60)

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    @property
    def db_path(self) -> str:
        """Absolute path to the SQLite database file."""
        return os.path.join(self.DATA_DIR, "app.db")

    def resolve_secret_key(self) -> str:
        """Prefer an explicit ``SECRET_KEY``; otherwise use the persisted one."""
        return os.environ.get("SECRET_KEY") or _persistent_secret(self.DATA_DIR)


class DevelopmentConfig(BaseConfig):
    """Local development: debug on, cookies allowed over plain HTTP."""

    ENV_NAME = "development"
    DEBUG = True


class ProductionConfig(BaseConfig):
    """Production: secure cookies (HTTPS only), debug off."""

    ENV_NAME = "production"
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(BaseConfig):
    """Automated tests: behave like development but flagged as testing."""

    ENV_NAME = "testing"
    DEBUG = True
    TESTING = True


_CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config() -> BaseConfig:
    """Instantiate the config class named by ``KAZA_ENV`` / ``FLASK_ENV``."""
    env = (os.environ.get("KAZA_ENV") or os.environ.get("FLASK_ENV") or "development").lower()
    config_cls = _CONFIGS.get(env, DevelopmentConfig)
    return config_cls()
