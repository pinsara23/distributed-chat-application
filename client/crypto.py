import os
import hashlib
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

PRIVATE_KEY_FILE = "local_identity.key"

class CryptoService:
    def __init__(self):
        self.prtivate_key = None
        self.public_key = None
        self.public_key_pem = None

    def load_or_generate_keys(self):
        """Loads the private key from disk, or generates a new X25519 key pair."""
        if os.path.exists(PRIVATE_KEY_FILE):
            with open(PRIVATE_KEY_FILE, "rb") as f:
                pem_data = f.read()
                self.prtivate_key = serialization.load_pem_private_key(
                    pem_data,
                    password=None
                )
            print("[Crypto] Loaded existing cryptographic identity from disk.")
        else:
            self.prtivate_key = x25519.X25519PrivateKey.generate()

            pem_data = self.prtivate_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            with open(PRIVATE_KEY_FILE, "wb") as f:
                f.write(pem_data)
            print("[Crypto] Generated new cryptographic identity and saved to disk.")

        # derive the public key from privayt key
        self.public_key = self.prtivate_key.public_key()

        # serialize the public key to PEM format for sharing
        self.public_key_pem = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("utf-8")

    def get_fingerprints(self, public_key_pem: str) -> dict:
        """Generates SHA256 and SHA512 fingerprints for a given public key PEM."""
        # Hash the raw string bytes
        digest = hashlib.sha256(public_key_pem.encode('utf-8')).hexdigest().upper()
        # Format it nicely: AB:12:CD:34...
        return ':'.join(digest[i:i+2] for i in range(0, len(digest), 2))

crypto_service = CryptoService()