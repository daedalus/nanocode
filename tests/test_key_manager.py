"""Tests for the Hardware Key Manager."""

import pytest
import tempfile
import os
from pathlib import Path

from nanocode.keyring import (
    HardwareKeyManager,
    KeyringManager,
    EnvKeyringManager,
    StoredCredential,
    get_key_manager,
    reset_key_manager,
)


class TestStoredCredential:
    """Tests for StoredCredential dataclass."""

    def test_creation(self):
        """Test creating a credential."""
        cred = StoredCredential(key="test", value="secret", provider="test")
        assert cred.key == "test"
        assert cred.value == "secret"


class TestHardwareKeyManager:
    """Tests for HardwareKeyManager."""

    def test_init(self, tmp_path):
        """Test initialization."""
        key_file = tmp_path / "keys.json"
        manager = HardwareKeyManager(key_file=str(key_file))
        assert manager.key_file == str(key_file)

    def test_get_machine_key(self):
        """Test machine key generation."""
        manager = HardwareKeyManager()
        key = manager._get_machine_key()
        assert len(key) == 44  # Base64 encoded 32 bytes

    def test_set_and_get_credential(self, tmp_path):
        """Test setting and getting credentials."""
        key_file = tmp_path / "keys.json"
        manager = HardwareKeyManager(key_file=str(key_file))

        manager.set_credential("test_key", "test_value")
        value = manager.get_credential("test_key")

        assert value == "test_value"

    def test_delete_credential(self, tmp_path):
        """Test deleting credentials."""
        key_file = tmp_path / "keys.json"
        manager = HardwareKeyManager(key_file=str(key_file))

        manager.set_credential("test_key", "test_value")
        deleted = manager.delete_credential("test_key")

        assert deleted is True
        assert manager.get_credential("test_key") is None

    def test_delete_nonexistent(self, tmp_path):
        """Test deleting non-existent credential."""
        key_file = tmp_path / "keys.json"
        manager = HardwareKeyManager(key_file=str(key_file))

        deleted = manager.delete_credential("nonexistent")
        assert deleted is False

    def test_list_credentials(self, tmp_path):
        """Test listing credentials."""
        key_file = tmp_path / "keys.json"
        manager = HardwareKeyManager(key_file=str(key_file))

        manager.set_credential("key1", "value1")
        manager.set_credential("key2", "value2")

        creds = manager.list_credentials()
        assert len(creds) == 2

    def test_persistence(self, tmp_path):
        """Test that credentials persist across instances."""
        key_file = tmp_path / "keys.json"

        # First instance
        manager1 = HardwareKeyManager(key_file=str(key_file))
        manager1.set_credential("persistent", "value")

        # Second instance
        manager2 = HardwareKeyManager(key_file=str(key_file))
        value = manager2.get_credential("persistent")

        assert value == "value"

    def test_get_api_key(self, tmp_path):
        """Test getting API key for provider."""
        key_file = tmp_path / "keys.json"
        manager = HardwareKeyManager(key_file=str(key_file))

        manager.set_credential("openai_api_key", "sk-test")

        api_key = manager.get_api_key("openai")
        assert api_key == "sk-test"

    def test_file_permissions(self, tmp_path):
        """Test that key file has restrictive permissions."""
        key_file = tmp_path / "keys.json"
        manager = HardwareKeyManager(key_file=str(key_file))

        manager.set_credential("test", "value")

        # Check permissions ( Unix only)
        if os.name != 'nt':
            mode = os.stat(key_file).st_mode & 0o777
            assert mode == 0o600

    def test_migration(self, tmp_path):
        """Test migrating from plaintext."""
        key_file = tmp_path / "keys.json"
        plaintext_file = tmp_path / "old_keys.json"

        # Create plaintext file
        import json
        with open(plaintext_file, "w") as f:
            json.dump({"old_key": "old_value"}, f)

        manager = HardwareKeyManager(key_file=str(key_file))
        migrated = manager.migrate_from_plaintext(str(plaintext_file))

        assert migrated == 1
        assert manager.get_credential("old_key") == "old_value"
        assert not plaintext_file.exists()
        assert (tmp_path / "old_keys.json.migrated").exists()


class TestGlobalInstance:
    """Tests for global instance."""

    def test_get_key_manager_singleton(self):
        """Test global instance is singleton."""
        reset_key_manager()
        m1 = get_key_manager()
        m2 = get_key_manager()
        assert m1 is m2

    def test_reset_key_manager(self):
        """Test resetting global instance."""
        m1 = get_key_manager()
        reset_key_manager()
        m2 = get_key_manager()
        assert m1 is not m2


class TestEnvKeyringManager:
    """Tests for EnvKeyringManager."""

    def test_init(self):
        """Test initialization."""
        manager = EnvKeyringManager(prefix="TEST")
        assert manager.prefix == "TEST"

    def test_get_from_env(self, monkeypatch):
        """Test getting credential from environment."""
        monkeypatch.setenv("TEST_API_KEY", "env_value")

        manager = EnvKeyringManager(prefix="TEST")
        value = manager.get_credential("api_key")

        assert value == "env_value"

    def test_get_api_key(self, monkeypatch):
        """Test getting API key for provider."""
        monkeypatch.setenv("NANOCODE_OPENAI_API_KEY", "sk-test")

        manager = EnvKeyringManager()
        api_key = manager.get_api_key("openai")

        assert api_key == "sk-test"
