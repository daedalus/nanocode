"""Tests for keyring module."""

import os
import tempfile

import pytest

from nanocode.keyring import (
    EnvKeyringManager,
    KeyringError,
    KeyringManager,
    SERVICE_NAME,
    StoredCredential,
    create_keyring_manager,
)


class TestStoredCredential:
    """Test StoredCredential dataclass."""

    def test_creation(self):
        """Test creating a credential."""
        cred = StoredCredential(key="api_key", value="secret123", provider="keyring")

        assert cred.key == "api_key"
        assert cred.value == "secret123"
        assert cred.provider == "keyring"


class TestKeyringManager:
    """Test KeyringManager."""

    def test_service_name(self):
        """Test default service name."""
        manager = KeyringManager()
        assert manager.service == SERVICE_NAME

    def test_custom_service(self):
        """Test custom service name."""
        manager = KeyringManager("myapp")
        assert manager.service == "myapp"

    def test_get_credential_not_found(self):
        """Test getting non-existent credential."""
        manager = KeyringManager()
        value = manager.get_credential("nonexistent_key_12345")

        assert value is None


class TestEnvKeyringManager:
    """Test EnvKeyringManager with environment fallback."""

    def test_env_fallback(self, monkeypatch):
        """Test environment variable fallback."""
        monkeypatch.setenv("NANOCODE_TEST_KEY", "env_secret")

        manager = EnvKeyringManager()
        value = manager.get_credential("test_key")

        assert value == "env_secret"

    def test_priority_keyring_over_env(self, monkeypatch):
        """Test keyring takes priority over environment."""
        monkeypatch.setenv("NANOCODE_PRIORITY_KEY", "env_value")

        manager = EnvKeyringManager()
        manager.set_credential("priority_key", "keyring_value")

        value = manager.get_credential("priority_key")
        assert value == "keyring_value"

    def test_get_api_key(self, monkeypatch):
        """Test get_api_key helper."""
        monkeypatch.setenv("NANOCODE_API_KEY", "my_api_key")

        manager = EnvKeyringManager()
        api_key = manager.get_api_key("test")

        assert api_key == "my_api_key"

    def test_get_api_key_provider_prefix(self, monkeypatch):
        """Test get_api_key with provider prefix."""
        monkeypatch.setenv("NANOCODE_OPENAI_API_KEY", "sk-openai")

        manager = EnvKeyringManager()
        api_key = manager.get_api_key("openai")

        assert api_key == "sk-openai"

    def test_get_api_key_not_found(self):
        """Test get_api_key returns None when not found."""
        manager = EnvKeyringManager()
        api_key = manager.get_api_key("nonexistent")

        assert api_key is None


class TestCreateKeyringManager:
    """Test factory function."""

    def test_create(self):
        """Test create_keyring_manager factory."""
        manager = create_keyring_manager()

        assert isinstance(manager, EnvKeyringManager)


class TestKeyringManagerIntegration:
    """Integration tests using real keyring if available."""

    def test_set_and_get_credential(self):
        """Test setting and getting a credential."""
        import uuid

        test_key = f"test_key_{uuid.uuid4().hex[:8]}"

        manager = KeyringManager()
        success = manager.set_credential(test_key, "test_value")
        value = manager.get_credential(test_key)

        if success:
            assert value == "test_value"
            manager.delete_credential(test_key)

    def test_delete_credential(self):
        """Test deleting a credential."""
        import uuid

        test_key = f"test_key_{uuid.uuid4().hex[:8]}"

        manager = KeyringManager()
        manager.set_credential(test_key, "test_value")
        success = manager.delete_credential(test_key)

        if success:
            value = manager.get_credential(test_key)
            assert value is None


class TestEnvKeyringCache:
    """Test environment variable caching."""

    def test_env_cache_updated_on_set(self, monkeypatch):
        """Test environment cache is updated when setting credential."""
        test_key = f"test_key"

        monkeypatch.delenv("NANOCODE_TEST_KEY", raising=False)

        manager = EnvKeyringManager()
        manager.set_credential(test_key, "cached_value")

        assert test_key in manager._env_cache
        assert manager._env_cache[test_key] == "cached_value"

    def test_env_cache_not_polluted(self, monkeypatch):
        """Test environment cache isolation."""
        monkeypatch.setenv("NANOCODE_OTHER_KEY", "env_value")

        manager = EnvKeyringManager()
        value = manager.get_credential("other_key")

        assert value == "env_value"