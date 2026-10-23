import pytest
import uuid
import json
from app.core.encryption import encryption_service
from app.messaging.redis_client import redis_manager

# --- 1. ENCRYPTION TESTS ---
def test_encryption_lifecycle():
    """Test that plaintext is securely encrypted and can be decrypted."""
    plaintext = "Hello Bob! This is a secret."
    
    # Encrypt
    ciphertext, nonce, version = encryption_service.encrypt(plaintext)
    
    # Prove it's encrypted
    assert ciphertext != plaintext
    assert b"Hello" not in ciphertext
    assert version == 1
    
    # Decrypt
    decrypted = encryption_service.decrypt(ciphertext, nonce)
    
    # Prove it matches original
    assert decrypted == plaintext

def test_encryption_determinism():
    """Prove that encrypting the same text twice yields different ciphertexts (thanks to unique nonces)."""
    plaintext = "Same exact message"
    
    cipher1, nonce1, _ = encryption_service.encrypt(plaintext)
    cipher2, nonce2, _ = encryption_service.encrypt(plaintext)
    
    assert cipher1 != cipher2
    assert nonce1 != nonce2

# --- 2. IDEMPOTENCY TESTS ---
@pytest.mark.asyncio
async def test_idempotency_check():
    """Test that Redis correctly flags duplicate events."""
    # Ensure Redis is connected for the test
    await redis_manager.connect()
    
    fake_event_id = str(uuid.uuid4())
    idempotency_key = f"processed_event:{fake_event_id}"
    
    # 1. First time seeing the event (should not exist)
    already_processed = await redis_manager.redis.exists(idempotency_key)
    assert not already_processed
    
    # 2. Mark as processed (simulate consumer success)
    await redis_manager.redis.set(idempotency_key, "1", ex=60)
    
    # 3. Second time seeing the event (should exist)
    is_duplicate = await redis_manager.redis.exists(idempotency_key)
    assert is_duplicate
    
    # Cleanup
    await redis_manager.redis.delete(idempotency_key)
    await redis_manager.disconnect()