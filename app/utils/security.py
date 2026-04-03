from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from cryptography.fernet import Fernet
from app.config import settings

# Patch bcrypt library BEFORE passlib imports it
# This is the only reliable way to prevent the 72-byte error during initialization
import sys
import bcrypt as _bcrypt_lib

# Store original hashpw
_original_bcrypt_hashpw = _bcrypt_lib.hashpw

def _truncated_bcrypt_hashpw(secret, salt):
    """Truncate secret to 72 bytes before calling bcrypt"""
    if isinstance(secret, (str, bytes)):
        secret_bytes = secret.encode('utf-8') if isinstance(secret, str) else secret
        if len(secret_bytes) > 72:
            secret_bytes = secret_bytes[:72]
            secret = secret_bytes if isinstance(secret, bytes) else secret_bytes.decode('utf-8', errors='ignore')
    return _original_bcrypt_hashpw(secret, salt)

# Replace bcrypt.hashpw globally - this affects all imports
_bcrypt_lib.hashpw = _truncated_bcrypt_hashpw

# Also patch in the module dict in case passlib imports it differently
if 'bcrypt' in sys.modules:
    sys.modules['bcrypt'].hashpw = _truncated_bcrypt_hashpw

from passlib.context import CryptContext

# Now create context - bcrypt.hashpw is already patched
# Use pbkdf2_sha256 as primary, bcrypt as fallback to avoid initialization issues
try:
    pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")
except Exception:
    # If that fails, use only pbkdf2_sha256
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    # Truncate password to 72 bytes if necessary (bcrypt limitation)
    password_bytes = plain_password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
        plain_password = password_bytes.decode('utf-8', errors='ignore')
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password"""
    # Truncate password to 72 bytes if necessary (bcrypt limitation)
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
        password = password_bytes.decode('utf-8', errors='ignore')
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT token"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def _get_fernet_key() -> bytes:
    """Get Fernet key from settings"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
    
    # Use PBKDF2 to derive a proper key from the encryption key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'cloudkraft_salt',  # In production, use a unique salt per user
        iterations=100000,
        backend=default_backend()
    )
    key = base64.urlsafe_b64encode(kdf.derive(settings.ENCRYPTION_KEY.encode()))
    return key


def encrypt_aws_credentials(credentials: str) -> str:
    """Encrypt AWS credentials"""
    f = Fernet(_get_fernet_key())
    return f.encrypt(credentials.encode()).decode()


def decrypt_aws_credentials(encrypted_credentials: str) -> str:
    """Decrypt AWS credentials"""
    f = Fernet(_get_fernet_key())
    return f.decrypt(encrypted_credentials.encode()).decode()

