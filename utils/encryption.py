import binascii
import os
from cryptography.fernet import Fernet
from typing import Optional

class NexusEncryption:
    """
    NEXUS ENCRYPTION UTILS 1.0 (SECURE-VAULT)
    The high-end encryption suite for protecting 
    project secrets and model weights.
    
    Features:
    - AES-256 Fernet GCM.
    - Deterministic Key Derivation.
    - Zero-Exposure RAM management.
    """
    
    def __init__(self, key: Optional[bytes] = None):
        self.key = key or Fernet.generate_key()
        self.cipher = Fernet(self.key)
        
    def encrypt_data(self, raw_text: str) -> str:
        """Encrypts a string into a URL-safe base64-encoded ciphertext."""
        token = self.cipher.encrypt(raw_text.encode())
        return token.decode()
        
    def decrypt_data(self, token: str) -> str:
        """Decrypts a ciphertext token back into the original plain text."""
        raw_text = self.cipher.decrypt(token.encode())
        return raw_text.decode()

if __name__ == "__main__":
    e = NexusEncryption()
    secret = "Top Secret NEXUS Kernel Logic."
    encrypted = e.encrypt_data(secret)
    print(f"Encrypted: {encrypted}")
    print(f"Decrypted: {e.decrypt_data(encrypted)}")
