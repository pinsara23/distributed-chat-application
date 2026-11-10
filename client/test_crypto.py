from crypto import CryptoService
from cryptography.exceptions import InvalidTag

print("--- 1. KEY GENERATION ---")
# Instantiate Alice and generate her keys
alice = CryptoService()
alice.private_key = alice._x25519 = __import__('cryptography.hazmat.primitives.asymmetric.x25519').hazmat.primitives.asymmetric.x25519.X25519PrivateKey.generate()
alice.public_key = alice.private_key.public_key()
alice.public_key_pem = alice.public_key.public_bytes(
    encoding=__import__('cryptography.hazmat.primitives.serialization').hazmat.primitives.serialization.Encoding.PEM,
    format=__import__('cryptography.hazmat.primitives.serialization').hazmat.primitives.serialization.PublicFormat.SubjectPublicKeyInfo
).decode('utf-8')
print("Alice generated her keys.")

# Instantiate Bob and generate his keys
bob = CryptoService()
bob.private_key = bob._x25519 = __import__('cryptography.hazmat.primitives.asymmetric.x25519').hazmat.primitives.asymmetric.x25519.X25519PrivateKey.generate()
bob.public_key = bob.private_key.public_key()
bob.public_key_pem = bob.public_key.public_bytes(
    encoding=__import__('cryptography.hazmat.primitives.serialization').hazmat.primitives.serialization.Encoding.PEM,
    format=__import__('cryptography.hazmat.primitives.serialization').hazmat.primitives.serialization.PublicFormat.SubjectPublicKeyInfo
).decode('utf-8')
print("Bob generated his keys.")

print("\n--- 2. KEY AGREEMENT (ECDH) ---")
# Alice derives the key using Bob's public PEM
alice_shared_key = alice.derive_shared_key(bob.public_key_pem)

# Bob derives the key using Alice's public PEM
bob_shared_key = bob.derive_shared_key(alice.public_key_pem)

print(f"Alice's AES Key: {alice_shared_key.hex()[:20]}...")
print(f"Bob's AES Key:   {bob_shared_key.hex()[:20]}...")
print(f"Match exactly?   {alice_shared_key == bob_shared_key} ✅")

print("\n--- 3. AUTHENTICATED ENCRYPTION ---")
plaintext = "Hello Bob, this is a top secret E2EE message!"
print(f"Original Text: {plaintext}")

ciphertext_b64, nonce_b64 = alice.encrypt_message(plaintext, alice_shared_key)
print(f"Ciphertext (to be sent over network): {ciphertext_b64}")
print(f"Nonce (to be sent over network):      {nonce_b64}")

print("\n--- 4. DECRYPTION ---")
decrypted = bob.decrypt_message(ciphertext_b64, nonce_b64, bob_shared_key)
print(f"Bob decrypted: {decrypted}")

print("\n--- 5. TAMPER DETECTION (GCM Authentication) ---")
# Simulate a hacker altering one character of the Base64 ciphertext
tampered_ciphertext = "A" + ciphertext_b64[1:] 
try:
    bob.decrypt_message(tampered_ciphertext, nonce_b64, bob_shared_key)
except InvalidTag:
    print("🚨 HACKER DETECTED! Decryption violently failed because the ciphertext was tampered with! ✅")