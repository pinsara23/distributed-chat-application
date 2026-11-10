import os
import hashlib
import base64
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PRIVATE_KEY_FILE = "local_identity.key"

class CryptoService:
    def __init__(self):
        self.private_key = None
        self.public_key = None
        self.public_key_pem = None

    def load_or_generate_keys(self):
        """Loads the private key from disk, or generates a new X25519 key pair."""
        if os.path.exists(PRIVATE_KEY_FILE):
            with open(PRIVATE_KEY_FILE, "rb") as f:
                pem_data = f.read()
                self.private_key = serialization.load_pem_private_key(pem_data, password=None)
            print("[Crypto] Loaded existing cryptographic identity from disk.")
        else:
            self.private_key = x25519.X25519PrivateKey.generate()
            pem_data = self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            with open(PRIVATE_KEY_FILE, "wb") as f:
                f.write(pem_data)
            print("[Crypto] Generated NEW cryptographic identity and saved to disk.")

        self.public_key = self.private_key.public_key()
        self.public_key_pem = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

    def get_fingerprint(self, public_key_pem: str) -> str:
        """Generates a readable SHA-256 fingerprint from a PEM public key."""
        digest = hashlib.sha256(public_key_pem.encode('utf-8')).hexdigest().upper()
        return ':'.join(digest[i:i+2] for i in range(0, len(digest), 2))

    def derive_shared_key(self, peer_public_key_pem: str) -> bytes:
        """
        Performs ECDH Key Agreement and derives a 256-bit AES key using HKDF.
        """
        # 1. Load the peer's public key from the PEM string
        peer_public_key = serialization.load_pem_public_key(peer_public_key_pem.encode('utf-8'))
        
        # 2. Mathematical ECDH Magic: My Private + Their Public = Shared Secret
        raw_shared_secret = self.private_key.exchange(peer_public_key)
        
        # 3. Pass through HKDF to derive a safe 256-bit (32-byte) AES key
        derived_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b'distributed-chat-e2ee-v1',
        ).derive(raw_shared_secret)
        
        return derived_key

    def encrypt_message(self, plaintext: str, shared_key: bytes) -> tuple[str, str]:
        """
        Encrypts a message using AES-GCM. 
        Returns (base64_ciphertext, base64_nonce)
        """
        aesgcm = AESGCM(shared_key)
        # GCM requires a strictly unique 12-byte nonce for every single message
        nonce = os.urandom(12) 
        
        # The ciphertext automatically has a 16-byte authentication tag appended to it
        ciphertext_bytes = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), associated_data=None)
        
        # Convert to Base64 strings for easy JSON transmission
        ciphertext_b64 = base64.b64encode(ciphertext_bytes).decode('utf-8')
        nonce_b64 = base64.b64encode(nonce).decode('utf-8')
        
        return ciphertext_b64, nonce_b64

    def decrypt_message(self, ciphertext_b64: str, nonce_b64: str, shared_key: bytes) -> str:
        """
        Decrypts an AES-GCM message and authenticates it.
        """
        aesgcm = AESGCM(shared_key)
        
        ciphertext_bytes = base64.b64decode(ciphertext_b64)
        nonce = base64.b64decode(nonce_b64)
        
        # If the ciphertext was tampered with, this will throw an InvalidTag exception!
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_bytes, associated_data=None)
        
        return plaintext_bytes.decode('utf-8')

crypto_service = CryptoService()