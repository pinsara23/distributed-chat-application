from datetime import datetime

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import BaseModel, ConfigDict, field_validator

MAX_PEM_LENGTH = 1024


class PublicKeyCreate(BaseModel):
    public_key_pem: str

    @field_validator("public_key_pem")
    @classmethod
    def must_be_x25519_public_key(cls, value: str) -> str:
        """Reject anything that is not a well-formed X25519 public key PEM."""
        if len(value) > MAX_PEM_LENGTH:
            raise ValueError("Public key is too large.")
        try:
            key = load_pem_public_key(value.encode("utf-8"))
        except Exception:
            raise ValueError("Not a valid PEM-encoded public key.")
        if not isinstance(key, x25519.X25519PublicKey):
            raise ValueError("Public key must be an X25519 key.")
        return value


class PublicKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    public_key_pem: str
    key_version: int
    created_at: datetime
