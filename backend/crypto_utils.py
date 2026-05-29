"""
API key encryption utilities for OpenCouncil.

Provides Fernet-based symmetric encryption for the Groq API key
so it can be stored encrypted in the database or config files.

For Vercel/GitHub deployment:
1. Generate an encryption key once: python -c "from crypto_utils import generate_key; print(generate_key())"
2. Set ENCRYPTION_KEY as a Vercel environment variable
3. Set GROK_API_KEY (encrypted) as a Vercel environment variable
4. The app decrypts at runtime using the ENCRYPTION_KEY

This means even if someone gets access to your DB or .env,
the API key is still encrypted with a separate key.
"""

import base64
import os
from typing import Optional

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


def generate_key() -> str:
    """Generate a new Fernet encryption key.
    
    Run this once and save the output as ENCRYPTION_KEY env var.
    
    Usage:
        python -c "from crypto_utils import generate_key; print(generate_key())"
    """
    if not HAS_CRYPTO:
        raise ImportError("Install cryptography: pip install cryptography")
    return Fernet.generate_key().decode()


def _get_fernet(encryption_key: Optional[str] = None) -> Fernet:
    """Get a Fernet instance using the provided key or ENCRYPTION_KEY env var."""
    if not HAS_CRYPTO:
        raise ImportError(
            "cryptography package is required for API key encryption. "
            "Install it with: pip install cryptography"
        )
    
    key = encryption_key or os.getenv("ENCRYPTION_KEY")
    if not key:
        raise ValueError(
            "ENCRYPTION_KEY is required. Generate one with: "
            "python -c \"from crypto_utils import generate_key; print(generate_key())\""
        )
    
    # Ensure key is bytes and properly formatted
    if isinstance(key, str):
        key = key.encode()
    
    return Fernet(key)


def encrypt_api_key(api_key: str, encryption_key: Optional[str] = None) -> str:
    """Encrypt an API key (e.g., DeepSeek key) for safe storage.
    
    Args:
        api_key: The plaintext API key to encrypt
        encryption_key: Optional custom encryption key (defaults to ENCRYPTION_KEY env var)
    
    Returns:
        Base64-encoded encrypted string
    """
    f = _get_fernet(encryption_key)
    encrypted = f.encrypt(api_key.encode())
    return encrypted.decode()


def decrypt_api_key(encrypted_key: str, encryption_key: Optional[str] = None) -> str:
    """Decrypt an API key that was encrypted with encrypt_api_key().
    
    Args:
        encrypted_key: The encrypted API key string
        encryption_key: Optional custom encryption key (defaults to ENCRYPTION_KEY env var)
    
    Returns:
        Plaintext API key
    """
    f = _get_fernet(encryption_key)
    decrypted = f.decrypt(encrypted_key.encode())
    return decrypted.decode()


def get_api_key_from_env() -> Optional[str]:
    """Get the Groq API key, supporting both plaintext and encrypted modes.
    
    Resolution order:
    1. GROK_API_KEY (plaintext) — for local dev
    2. ENCRYPTED_GROK_KEY + ENCRYPTION_KEY — for production/GitHub-safe deploy
    
    Returns:
        The decrypted API key, or None if not configured.
    """
    # First try plaintext (local dev)
    plain_key = os.getenv("GROK_API_KEY")
    if plain_key:
        return plain_key
    
    # Then try encrypted (production/GitHub-safe)
    encrypted_key = os.getenv("ENCRYPTED_GROK_KEY")
    encryption_key = os.getenv("ENCRYPTION_KEY")
    
    if encrypted_key and encryption_key:
        try:
            return decrypt_api_key(encrypted_key, encryption_key)
        except Exception as e:
            print(f"[WARN] Failed to decrypt API key: {e}")
            return None
    
    return None
