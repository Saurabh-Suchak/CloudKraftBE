import secrets as _secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt as _pyjwt
from jwt.exceptions import InvalidTokenError as _InvalidTokenError
from cryptography.fernet import Fernet
from argon2 import PasswordHasher as _PasswordHasher
from argon2.exceptions import VerifyMismatchError as _VerifyMismatchError
from app.config import settings

_ph = _PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
)

# Static fallback salt used only for credentials encrypted before per-user salts were
# introduced.  Must never be reused for new encryptions.
_LEGACY_SALT = b'cloudkraft_salt'


def _verify_legacy(plain_password: str, hashed_password: str) -> bool:
    """Verify a pbkdf2_sha256 or bcrypt hash produced by the old passlib stack."""
    try:
        from passlib.context import CryptContext
        _legacy_ctx = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")
        return _legacy_ctx.verify(plain_password, hashed_password)
    except Exception:
        return False


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Argon2 hashes start with "$argon2"
    if hashed_password.startswith("$argon2"):
        try:
            return _ph.verify(hashed_password, plain_password)
        except _VerifyMismatchError:
            return False
        except Exception:
            return False
    # Fall back to legacy passlib verification for existing accounts
    return _verify_legacy(plain_password, hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    """Return True if the hash should be upgraded to argon2 on next login."""
    return not hashed_password.startswith("$argon2")


def get_password_hash(password: str) -> str:
    return _ph.hash(password)


def generate_credential_salt() -> str:
    return _secrets.token_hex(32)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "jti": _secrets.token_hex(16)})
    return _pyjwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = _pyjwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except _InvalidTokenError:
        return None


def _derive_fernet_key(salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,
        backend=default_backend(),
    )
    return base64.urlsafe_b64encode(kdf.derive(settings.ENCRYPTION_KEY.encode()))


def encrypt_aws_credentials(credentials: str, user_salt: Optional[str] = None) -> str:
    salt = bytes.fromhex(user_salt) if user_salt else _LEGACY_SALT
    return Fernet(_derive_fernet_key(salt)).encrypt(credentials.encode()).decode()


def decrypt_aws_credentials(encrypted_credentials: str, user_salt: Optional[str] = None) -> str:
    salt = bytes.fromhex(user_salt) if user_salt else _LEGACY_SALT
    return Fernet(_derive_fernet_key(salt)).decrypt(encrypted_credentials.encode()).decode()


def revoke_token(jti: str, expires_at: datetime, db) -> None:
    from app.models.audit import RevokedToken
    db.add(RevokedToken(jti=jti, expires_at=expires_at))
    db.commit()


def is_token_revoked(jti: str, db) -> bool:
    from app.models.audit import RevokedToken
    return db.query(RevokedToken).filter(RevokedToken.jti == jti).first() is not None

