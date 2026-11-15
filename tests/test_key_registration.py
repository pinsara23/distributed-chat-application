import pytest
from pydantic import ValidationError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from app.schemas.key import PublicKeyCreate
from app.services.key_service import KeyService


def _pem(private_key) -> str:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def test_valid_x25519_key_is_accepted():
    pem = _pem(x25519.X25519PrivateKey.generate())
    assert PublicKeyCreate(public_key_pem=pem).public_key_pem == pem


@pytest.mark.parametrize("bad", ["", "not a pem", "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n"])
def test_garbage_is_rejected(bad):
    with pytest.raises(ValidationError):
        PublicKeyCreate(public_key_pem=bad)


def test_wrong_key_type_is_rejected():
    pem = _pem(ed25519.Ed25519PrivateKey.generate())
    with pytest.raises(ValidationError):
        PublicKeyCreate(public_key_pem=pem)


class _Result:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class _Session:
    def __init__(self, row):
        self.row = row
        self.commits = 0

    async def execute(self, _stmt):
        return _Result(self.row)

    def add(self, obj):
        self.row = obj

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj):
        pass


class _Key:
    def __init__(self, pem, version=1):
        self.public_key_pem, self.key_version = pem, version


async def test_reuploading_same_key_does_not_bump_version():
    pem = _pem(x25519.X25519PrivateKey.generate())
    session = _Session(_Key(pem, version=3))
    result = await KeyService(session).upload_or_update_key(1, pem)
    assert result.key_version == 3
    assert session.commits == 0


async def test_changed_key_bumps_version():
    old, new = (_pem(x25519.X25519PrivateKey.generate()) for _ in range(2))
    session = _Session(_Key(old, version=3))
    result = await KeyService(session).upload_or_update_key(1, new)
    assert result.key_version == 4
    assert result.public_key_pem == new
