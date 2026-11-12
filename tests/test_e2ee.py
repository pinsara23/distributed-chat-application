import os
import sys
import pytest
from cryptography.exceptions import InvalidTag

# Add client folder to Python path so we can import our crypto module safely
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../client')))
from crypto import CryptoService

@pytest.fixture
def setup_users():
    """Fixture to generate Alice, Bob, and Charlie for testing without writing to disk."""
    alice = CryptoService()
    bob = CryptoService()
    charlie = CryptoService()
    
    from cryptography.hazmat.primitives.asymmetric import x25519
    from cryptography.hazmat.primitives import serialization
    
    # Generate keys in-memory for fast testing
    for user in [alice, bob, charlie]:
        user.private_key = x25519.X25519PrivateKey.generate()
        user.public_key = user.private_key.public_key()
        user.public_key_pem = user.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        
    return alice, bob, charlie

def test_deterministic_fingerprint(setup_users):
    """Test: A public key must always generate the exact same fingerprint."""
    alice, _, _ = setup_users
    fingerprint1 = alice.get_fingerprint(alice.public_key_pem)
    fingerprint2 = alice.get_fingerprint(alice.public_key_pem)
    
    assert fingerprint1 == fingerprint2
    assert len(fingerprint1.split(':')) == 32  # SHA-256 is 32 bytes

def test_ecdh_key_agreement(setup_users):
    """Test: Alice and Bob must independently derive the exact same AES Shared Key."""
    alice, bob, _ = setup_users
    
    alice_shared = alice.derive_shared_key(bob.public_key_pem)
    bob_shared = bob.derive_shared_key(alice.public_key_pem)
    
    assert alice_shared == bob_shared
    assert len(alice_shared) == 32  # 256-bit AES key

def test_e2ee_encryption_decryption(setup_users):
    """Test: Happy Path - Alice encrypts, Bob perfectly decrypts."""
    alice, bob, _ = setup_users
    alice_shared = alice.derive_shared_key(bob.public_key_pem)
    bob_shared = bob.derive_shared_key(alice.public_key_pem)
    
    plaintext = "This is a top secret E2EE message!"
    ciphertext_b64, nonce_b64 = alice.encrypt_message(plaintext, alice_shared)
    
    # Prove the server cannot see the plaintext (it is not in the Base64)
    assert plaintext not in ciphertext_b64
    
    decrypted = bob.decrypt_message(ciphertext_b64, nonce_b64, bob_shared)
    assert decrypted == plaintext

def test_tamper_detection(setup_users):
    """Test: If a hacker alters the ciphertext, decryption MUST fail violently."""
    alice, bob, _ = setup_users
    alice_shared = alice.derive_shared_key(bob.public_key_pem)
    bob_shared = bob.derive_shared_key(alice.public_key_pem)
    
    plaintext = "Don't change this!"
    ciphertext_b64, nonce_b64 = alice.encrypt_message(plaintext, alice_shared)
    
    # Hacker tampers with the ciphertext (changes the first character)
    tampered_ciphertext = "A" + ciphertext_b64[1:]
    
    # AES-GCM must throw an InvalidTag exception!
    with pytest.raises(InvalidTag):
        bob.decrypt_message(tampered_ciphertext, nonce_b64, bob_shared)

def test_wrong_key_decryption(setup_users):
    """Test: If Charlie tries to decrypt Alice's message to Bob, it MUST fail."""
    alice, bob, charlie = setup_users
    
    # Alice encrypts for Bob
    alice_shared = alice.derive_shared_key(bob.public_key_pem)
    plaintext = "For Bob's eyes only!"
    ciphertext_b64, nonce_b64 = alice.encrypt_message(plaintext, alice_shared)
    
    # Charlie mathematically derives a key using Alice's public key
    charlie_shared = charlie.derive_shared_key(alice.public_key_pem)
    
    # Charlie tries to decrypt Bob's message
    with pytest.raises(InvalidTag):
        charlie.decrypt_message(ciphertext_b64, nonce_b64, charlie_shared)