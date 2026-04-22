"""Secure keyring-based credential storage."""

import logging
import os
from dataclasses import dataclass
from typing import Optional

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

    def get_credential(self, key: str) -> Optional[str]:
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

    def get_credential(self, key: str) -> Optional[str]:
        """Get credential, first checking keyring, then environment."""
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

    def get_api_key(self, provider: str) -> Optional[str]:
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


def create_keyring_manager(service: str = None) -> KeyringManager:
    """Create a keyring manager."""
    return EnvKeyringManager(service)