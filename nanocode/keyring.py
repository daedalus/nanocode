"""Secure keyring-based credential storage."""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SERVICE_NAME = "nanocode"


@dataclass
class StoredCredential:
    """A stored credential."""

    key: str
    value: str
    provider: str


class KeyringError(Exception):
    """Base exception for keyring errors."""

    pass


class KeyringManager:
    """Manages credentials using OS keyring."""

    def __init__(self, service: str = None):
        self.service = service or SERVICE_NAME

    def set_credential(self, key: str, value: str) -> bool:
        """Store a credential securely."""
        try:
            import keyring

            keyring.set_password(self.service, key, value)
            logger.info(f"Stored credential: {key}")
            return True
        except Exception as e:
            logger.warning(f"Failed to store credential {key}: {e}")
            return False

    def get_credential(self, key: str) -> str | None:
        """Retrieve a credential."""
        try:
            import keyring

            return keyring.get_password(self.service, key)
        except Exception as e:
            logger.warning(f"Failed to retrieve credential {key}: {e}")
            return None

    def delete_credential(self, key: str) -> bool:
        """Delete a credential."""
        try:
            import keyring

            keyring.delete_password(self.service, key)
            logger.info(f"Deleted credential: {key}")
            return True
        except Exception as e:
            logger.warning(f"Failed to delete credential {key}: {e}")
            return False

    def list_credentials(self) -> list[StoredCredential]:
        """List all stored credentials."""
        credentials = []

        try:
            import keyring

            for name in keyring.get_password(self.service, None) or []:
                value = keyring.get_password(self.service, name)
                if value:
                    credentials.append(
                        StoredCredential(
                            key=name,
                            value=value,
                            provider="keyring",
                        )
                    )
        except Exception as e:
            logger.warning(f"Failed to list credentials: {e}")

        return credentials


class EnvKeyringManager(KeyringManager):
    """Keyring manager that falls back to environment variables."""

    def __init__(self, service: str = None, prefix: str = None):
        super().__init__(service)
        self.prefix = prefix or "NANOCODE"
        self._env_cache: dict[str, str] = {}

    def get_credential(self, key: str) -> str | None:
        """Get credential, first checking keyring, then environment."""
        if key in self._env_cache:
            return self._env_cache[key]
        value = super().get_credential(key)
        if value:
            return value

        env_key = f"{self.prefix}_{key.upper()}"
        value = os.getenv(env_key)
        if value:
            self._env_cache[key] = value
            return value

        return None

    def set_credential(self, key: str, value: str) -> bool:
        """Store credential in keyring."""
        self._env_cache[key] = value
        return super().set_credential(key, value)

    def get_api_key(self, provider: str) -> str | None:
        """Get API key for a provider common names."""
        common_keys = [
            f"{provider}_api_key",
            f"{provider.upper()}_API_KEY",
            "api_key",
        ]

        for key in common_keys:
            value = self.get_credential(key)
            if value:
                return value

        return None


class HardwareKeyManager:
    """Hardware-tethered key manager for when OS keyring is unavailable.

    Based on Aura's approach:
    - Machine key derived from uuid.getnode() + os.getlogin()
    - SHA-256 → base64 Fernet key
    - Stores encrypted keys at ~/.config/nanocode/keys.json
    - Auto-migrates legacy plaintext keys
    """

    DEFAULT_KEY_FILE = "~/.config/nanocode/keys.json"

    def __init__(self, key_file: str = None):
        """Initialize the hardware key manager.

        Args:
            key_file: Path to encrypted keys file
        """
        if key_file is None:
            key_file = self.DEFAULT_KEY_FILE
        self.key_file = os.path.expanduser(key_file)
        self._machine_key = None
        self._keys: dict[str, str] = {}

    def _get_machine_key(self) -> bytes:
        """Derive machine-specific encryption key."""
        if self._machine_key is not None:
            return self._machine_key

        import base64
        import hashlib
        import uuid

        # Get machine identifiers
        node = str(uuid.getnode())
        try:
            import getpass
            login = getpass.getuser()
        except Exception:
            login = "unknown"

        # Create deterministic key material
        key_material = f"{node}:{login}:nanocode-encryption-key"
        key_hash = hashlib.sha256(key_material.encode()).digest()

        # Use Fernet-compatible key (32 bytes base64 encoded)
        self._machine_key = base64.urlsafe_b64encode(key_hash)
        return self._machine_key

    def _get_fernet(self):
        """Get Fernet instance for encryption."""
        try:
            from cryptography.fernet import Fernet
            return Fernet(self._get_machine_key())
        except ImportError:
            logger.warning("cryptography library not available")
            return None

    def _load_keys(self) -> dict[str, str]:
        """Load encrypted keys from file."""
        if self._keys:
            return self._keys

        if not os.path.exists(self.key_file):
            return {}

        try:
            with open(self.key_file) as f:
                data = __import__("json").load(f)

            fernet = self._get_fernet()
            if not fernet:
                return data.get("keys", {})

            # Decrypt values
            encrypted_keys = data.get("keys", {})
            decrypted = {}
            for key, value in encrypted_keys.items():
                try:
                    decrypted_value = fernet.decrypt(value.encode()).decode()
                    decrypted[key] = decrypted_value
                except Exception:
                    # Value might be plaintext (legacy)
                    decrypted[key] = value

            self._keys = decrypted
            return decrypted

        except Exception as e:
            logger.warning(f"Failed to load keys: {e}")
            return {}

    def _save_keys(self):
        """Save keys to file with encryption."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.key_file), exist_ok=True)

            fernet = self._get_fernet()
            if fernet:
                # Encrypt values
                encrypted = {}
                for key, value in self._keys.items():
                    encrypted[key] = fernet.encrypt(value.encode()).decode()
                data = {"keys": encrypted}
            else:
                data = {"keys": self._keys}

            with open(self.key_file, "w") as f:
                __import__("json").dump(data, f, indent=2)

            # Set restrictive permissions
            os.chmod(self.key_file, 0o600)

            logger.debug(f"Saved {len(self._keys)} keys to {self.key_file}")

        except Exception as e:
            logger.error(f"Failed to save keys: {e}")

    def get_credential(self, key: str) -> str | None:
        """Get a credential by key."""
        keys = self._load_keys()
        return keys.get(key)

    def set_credential(self, key: str, value: str) -> bool:
        """Store a credential."""
        self._keys[key] = value
        self._save_keys()
        return True

    def delete_credential(self, key: str) -> bool:
        """Delete a credential."""
        if key in self._keys:
            del self._keys[key]
            self._save_keys()
            return True
        return False

    def list_credentials(self) -> list[StoredCredential]:
        """List all stored credentials."""
        keys = self._load_keys()
        return [
            StoredCredential(key=k, value=v, provider="hardware")
            for k, v in keys.items()
        ]

    def migrate_from_plaintext(self, plaintext_file: str) -> int:
        """Migrate plaintext keys to encrypted storage.

        Args:
            plaintext_file: Path to plaintext keys file

        Returns:
            Number of keys migrated
        """
        if not os.path.exists(plaintext_file):
            return 0

        try:
            with open(plaintext_file) as f:
                plaintext_keys = __import__("json").load(f)

            migrated = 0
            for key, value in plaintext_keys.items():
                if key not in self._keys:
                    self._keys[key] = value
                    migrated += 1

            if migrated > 0:
                self._save_keys()
                # Rename old file
                os.rename(plaintext_file, f"{plaintext_file}.migrated")
                logger.info(f"Migrated {migrated} keys from plaintext")

            return migrated

        except Exception as e:
            logger.error(f"Failed to migrate keys: {e}")
            return 0

    def get_api_key(self, provider: str) -> str | None:
        """Get API key for a provider."""
        common_keys = [
            f"{provider}_api_key",
            f"{provider.upper()}_API_KEY",
            "api_key",
        ]

        for key in common_keys:
            value = self.get_credential(key)
            if value:
                return value

        return None


# Global instance
_hw_key_manager: HardwareKeyManager | None = None


def get_key_manager() -> HardwareKeyManager:
    """Get or create the global hardware key manager."""
    global _hw_key_manager
    if _hw_key_manager is None:
        _hw_key_manager = HardwareKeyManager()
    return _hw_key_manager


def reset_key_manager():
    """Reset the global hardware key manager."""
    global _hw_key_manager
    _hw_key_manager = None


def create_keyring_manager(service: str = None) -> KeyringManager:
    """Create a keyring manager."""
    return EnvKeyringManager(service)
