import os
from app.core.config import settings
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class MessageEncryptionService:
    def __init__(self, hex_key: str):
        # convert hex key in .env to raw bytes for AESGCM
        self.key = bytes.fromhex(hex_key)

        self.version = 1

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes, int]:
        """Encrypt a message using AES-GCM."""
        # (cyperthext, nonce, version)
        aesgcm = AESGCM(self.key)
        nonce = os.urandom(12)  # AESGCM standard nonce size is 12 bytes

        # convert plaintext to bytes
        plaintext_bytes = plaintext.encode("utf-8")

        cypertext = aesgcm.encrypt(nonce, plaintext_bytes, associated_data=None)

        return cypertext, nonce, self.version 

    def decrypt(self, cypertext: bytes, nonce: bytes) -> str:
        """Decrypt a message using AES-GCM."""
        aesgcm = AESGCM(self.key)

        plaintext_bytes = aesgcm.decrypt(nonce, cypertext, associated_data=None)

        return plaintext_bytes.decode("utf-8")  # convert bytes to string

encryption_service = MessageEncryptionService(settings.MESSAGE_ENCRYPTION_KEY)
    