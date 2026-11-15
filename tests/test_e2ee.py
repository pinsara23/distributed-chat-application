import os
import sys
import uuid
from types import SimpleNamespace
import pytest
from cryptography.exceptions import InvalidTag

# Add client folder to Python path so we can import our crypto module safely
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../client')))
from crypto import CryptoService, build_aad, PROTOCOL_VERSION

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

MSG_ID = "3f2b8c1e-5a47-4d0a-9b6e-1c2d3e4f5a6b"
CONV_ID = 7
ALICE_ID = 1


def _flip_first_char(b64: str) -> str:
    return ("B" if b64[0] == "A" else "A") + b64[1:]


@pytest.fixture
def sealed(setup_users):
    """Alice encrypts one message for Bob; returns everything the receiver sees."""
    alice, bob, charlie = setup_users
    alice_shared = alice.derive_shared_key(bob.public_key_pem)
    bob_shared = bob.derive_shared_key(alice.public_key_pem)
    aad = build_aad(MSG_ID, CONV_ID, ALICE_ID)
    ciphertext_b64, nonce_b64 = alice.encrypt_message("This is a top secret E2EE message!", alice_shared, aad)
    return SimpleNamespace(
        alice=alice, bob=bob, charlie=charlie, bob_shared=bob_shared,
        ciphertext=ciphertext_b64, nonce=nonce_b64, aad=aad,
    )


def test_e2ee_encryption_decryption(sealed):
    """Happy path: Alice encrypts, Bob decrypts with the same AAD."""
    # The server cannot see the plaintext (it is not in the Base64)
    assert "top secret" not in sealed.ciphertext
    assert sealed.bob.decrypt_message(
        sealed.ciphertext, sealed.nonce, sealed.bob_shared, sealed.aad
    ) == "This is a top secret E2EE message!"


def test_tamper_detection(sealed):
    """If someone alters the ciphertext, decryption MUST fail."""
    with pytest.raises(InvalidTag):
        sealed.bob.decrypt_message(
            _flip_first_char(sealed.ciphertext), sealed.nonce, sealed.bob_shared, sealed.aad
        )


def test_wrong_key_decryption(sealed):
    """Charlie cannot decrypt Alice's message to Bob."""
    charlie_shared = sealed.charlie.derive_shared_key(sealed.alice.public_key_pem)
    with pytest.raises(InvalidTag):
        sealed.charlie.decrypt_message(sealed.ciphertext, sealed.nonce, charlie_shared, sealed.aad)


# --- AAD binding ------------------------------------------------------------

def test_tampered_aad_fails(sealed):
    """Any change to the authenticated header must break decryption."""
    forged = sealed.aad + b"x"
    with pytest.raises(InvalidTag):
        sealed.bob.decrypt_message(sealed.ciphertext, sealed.nonce, sealed.bob_shared, forged)


def test_wrong_conversation_fails(sealed):
    """A ciphertext cannot be moved into another conversation."""
    with pytest.raises(InvalidTag):
        sealed.bob.decrypt_message(
            sealed.ciphertext, sealed.nonce, sealed.bob_shared,
            build_aad(MSG_ID, CONV_ID + 1, ALICE_ID),
        )


def test_wrong_sender_fails(sealed):
    """The server cannot claim a different sender for the same ciphertext."""
    with pytest.raises(InvalidTag):
        sealed.bob.decrypt_message(
            sealed.ciphertext, sealed.nonce, sealed.bob_shared,
            build_aad(MSG_ID, CONV_ID, ALICE_ID + 1),
        )


def test_wrong_message_id_fails(sealed):
    """A ciphertext cannot be replayed under a different message id."""
    with pytest.raises(InvalidTag):
        sealed.bob.decrypt_message(
            sealed.ciphertext, sealed.nonce, sealed.bob_shared,
            build_aad(str(uuid.uuid4()), CONV_ID, ALICE_ID),
        )


def test_wrong_protocol_version_fails(sealed):
    with pytest.raises(InvalidTag):
        sealed.bob.decrypt_message(
            sealed.ciphertext, sealed.nonce, sealed.bob_shared,
            build_aad(MSG_ID, CONV_ID, ALICE_ID, protocol_version=PROTOCOL_VERSION + 1),
        )


def test_aad_serialization_is_canonical():
    assert build_aad(MSG_ID, CONV_ID, ALICE_ID) == (
        b"dchat-e2ee|v1|3f2b8c1e-5a47-4d0a-9b6e-1c2d3e4f5a6b|7|1"
    )
    # uuid spelling does not matter: it is normalized
    assert build_aad(MSG_ID.upper(), CONV_ID, ALICE_ID) == build_aad(MSG_ID, CONV_ID, ALICE_ID)
    assert build_aad(uuid.UUID(MSG_ID), CONV_ID, ALICE_ID) == build_aad(MSG_ID, CONV_ID, ALICE_ID)


@pytest.mark.parametrize("conv,sender", [(0, 1), (1, 0), (-1, 1), ("7", 1), (True, 1), (1.5, 1)])
def test_aad_rejects_non_canonical_integers(conv, sender):
    with pytest.raises(ValueError):
        build_aad(MSG_ID, conv, sender)


def test_aad_rejects_bad_message_id():
    with pytest.raises(ValueError):
        build_aad("not-a-uuid", 1, 1)
