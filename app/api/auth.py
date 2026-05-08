import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.limiter import limiter
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.user import (
    AWSStatusResponse,
    ChangePasswordRequest,
    ConnectAWSRequest,
    EnvVarsRequest,
    EnvVarsResponse,
    Token,
    UpdateProfileRequest,
    UserAWSRegister,
    UserCreate,
    UserResponse,
)
from app.utils.security import (
    create_access_token,
    decode_access_token,
    decrypt_aws_credentials,
    encrypt_aws_credentials,
    generate_credential_salt,
    get_password_hash,
    is_token_revoked,
    needs_rehash,
    revoke_token,
    verify_password,
)
from app.config import settings

import secrets as _secrets

router = APIRouter(prefix="/api/auth", tags=["authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_decrypt(user, field: str, db: Session) -> Optional[str]:
    """Decrypt a user credential field, re-encrypting with the current key on InvalidToken.

    Handles the case where the field was encrypted before a key rotation — decryption fails
    for UUIDs (external_id) we can just regenerate; for real secrets (aws keys) we clear
    them so the user is prompted to reconnect rather than serving a 500.
    """
    from cryptography.fernet import InvalidToken
    value = getattr(user, field)
    if not value:
        return None
    try:
        return decrypt_aws_credentials(value, user_salt=user.credential_salt)
    except (InvalidToken, Exception):
        if field == "external_id":
            new_val = str(uuid.uuid4())
            setattr(user, field, encrypt_aws_credentials(new_val, user_salt=user.credential_salt))
            db.commit()
            return new_val
        # Real credential — clear it; user must reconnect
        setattr(user, field, None)
        db.commit()
        return None


def _write_audit(db: Session, action: str, user_id=None, resource_type=None,
                 resource_id=None, ip=None, details=None):
    db.add(AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip,
        details=json.dumps(details) if details else None,
    ))
    db.commit()


def _resolve_token(
    header_token: Optional[str],
    cookie_token: Optional[str],
) -> Optional[str]:
    return header_token or cookie_token


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    auth_token: Optional[str] = Cookie(default=None),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Accept token from Authorization header or httpOnly cookie
    header_value = request.headers.get("Authorization", "")
    header_token = header_value.removeprefix("Bearer ").strip() if header_value.startswith("Bearer ") else None
    token = _resolve_token(header_token, auth_token)
    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception

    jti = payload.get("jti")
    if jti and is_token_revoked(jti, db):
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception

    return user


# ---------------------------------------------------------------------------
# Registration / login
# ---------------------------------------------------------------------------

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def register(request: Request, response: Response, user_data: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    salt = generate_credential_salt()
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        email=user_data.email,
        password_hash=hashed_password,
        full_name=user_data.full_name,
        credential_salt=salt,
        external_id=encrypt_aws_credentials(str(uuid.uuid4()), user_salt=salt),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    token = create_access_token(data={"sub": db_user.email})
    _set_auth_cookie(response, token)
    _write_audit(db, "register", user_id=db_user.id,
                 ip=request.client.host if request.client else None)
    return db_user


def _set_auth_cookie(response: Response, token: str) -> None:
    max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie(
        key="auth_token",
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == form_data.username).first()

    password_ok = verify_password(form_data.password, user.password_hash) if user else False
    if not user or not password_ok:
        _write_audit(db, "login_failed", ip=request.client.host if request.client else None,
                     details={"email": form_data.username})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if needs_rehash(user.password_hash):
        user.password_hash = get_password_hash(form_data.password)
        db.commit()

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    _set_auth_cookie(response, access_token)
    _write_audit(db, "login", user_id=user.id,
                 ip=request.client.host if request.client else None)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="auth_token", path="/", samesite="lax")
    return {"message": "Logged out"}


@router.post("/aws-register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def register_with_aws(request: Request, user_data: UserAWSRegister, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    try:
        sts = boto3.client(
            "sts",
            aws_access_key_id=user_data.aws_access_key,
            aws_secret_access_key=user_data.aws_secret_key,
            region_name=user_data.aws_region,
        )
        sts.get_caller_identity()
    except (ClientError, NoCredentialsError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid AWS credentials: {e}")

    salt = generate_credential_salt()
    db_user = User(
        email=user_data.email,
        password_hash=get_password_hash(_secrets.token_urlsafe(32)),
        full_name=user_data.full_name,
        credential_salt=salt,
        aws_access_key=encrypt_aws_credentials(user_data.aws_access_key, user_salt=salt),
        aws_secret_key=encrypt_aws_credentials(user_data.aws_secret_key, user_salt=salt),
        aws_region=user_data.aws_region,
        auth_method="access_key",
        external_id=encrypt_aws_credentials(str(uuid.uuid4()), user_salt=salt),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    _write_audit(db, "aws_register", user_id=db_user.id,
                 ip=request.client.host if request.client else None)
    return db_user


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# AWS credential management
# ---------------------------------------------------------------------------

@router.post("/connect-aws", response_model=AWSStatusResponse)
@limiter.limit("20/minute")
def connect_aws(
    request: Request,
    aws_request: ConnectAWSRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError

    if not current_user.credential_salt:
        current_user.credential_salt = generate_credential_salt()
        db.commit()

    salt = current_user.credential_salt

    if aws_request.auth_method == "access_key":
        if not aws_request.access_key or not aws_request.secret_key:
            raise HTTPException(status_code=400, detail="access_key and secret_key required")

        try:
            sts = boto3.client(
                "sts",
                aws_access_key_id=aws_request.access_key,
                aws_secret_access_key=aws_request.secret_key,
                region_name=aws_request.region,
            )
            sts.get_caller_identity()
        except (ClientError, NoCredentialsError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid AWS credentials: {e}")

        current_user.auth_method = "access_key"
        current_user.aws_access_key = encrypt_aws_credentials(aws_request.access_key, user_salt=salt)
        current_user.aws_secret_key = encrypt_aws_credentials(aws_request.secret_key, user_salt=salt)
        current_user.aws_region = aws_request.region
        current_user.role_arn = None

    elif aws_request.auth_method == "assume_role":
        if not aws_request.role_arn:
            raise HTTPException(status_code=400, detail="role_arn required for assume_role")

        if settings.BACKEND_AWS_ACCESS_KEY and settings.BACKEND_AWS_SECRET_KEY:
            try:
                sts = boto3.client(
                    "sts",
                    aws_access_key_id=settings.BACKEND_AWS_ACCESS_KEY,
                    aws_secret_access_key=settings.BACKEND_AWS_SECRET_KEY,
                    region_name=aws_request.region or settings.BACKEND_AWS_REGION,
                )
                assume_params: dict = {
                    "RoleArn": aws_request.role_arn,
                    "RoleSessionName": "cloudkraft-validation",
                }
                if aws_request.external_id:
                    assume_params["ExternalId"] = aws_request.external_id
                sts.assume_role(**assume_params)
            except (ClientError, NoCredentialsError) as e:
                raise HTTPException(status_code=400, detail=f"Could not assume role: {e}")

        current_user.auth_method = "assume_role"
        current_user.role_arn = aws_request.role_arn
        if aws_request.external_id:
            current_user.external_id = encrypt_aws_credentials(aws_request.external_id, user_salt=salt)
        current_user.aws_region = aws_request.region
        current_user.aws_access_key = None
        current_user.aws_secret_key = None

    db.commit()
    db.refresh(current_user)

    ext_id_plain = _safe_decrypt(current_user, "external_id", db)
    _write_audit(db, "aws_connect", user_id=current_user.id,
                 ip=request.client.host if request.client else None,
                 details={"auth_method": current_user.auth_method})
    return AWSStatusResponse(
        connected=True,
        auth_method=current_user.auth_method,
        region=current_user.aws_region,
        role_arn=current_user.role_arn,
        external_id=ext_id_plain,
    )


@router.post("/disconnect-aws")
def disconnect_aws(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.auth_method = None
    current_user.aws_access_key = None
    current_user.aws_secret_key = None
    current_user.aws_region = None
    current_user.role_arn = None
    db.commit()
    return {"message": "AWS account disconnected"}


@router.get("/aws-status", response_model=AWSStatusResponse)
def aws_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user.credential_salt:
        current_user.credential_salt = generate_credential_salt()
        db.commit()
        db.refresh(current_user)

    if not current_user.external_id:
        salt = current_user.credential_salt
        current_user.external_id = encrypt_aws_credentials(str(uuid.uuid4()), user_salt=salt)
        db.commit()
        db.refresh(current_user)

    connected = bool(
        (current_user.auth_method == "access_key" and current_user.aws_access_key)
        or (current_user.auth_method == "assume_role" and current_user.role_arn)
    )
    return AWSStatusResponse(
        connected=connected,
        auth_method=current_user.auth_method,
        region=current_user.aws_region,
        role_arn=current_user.role_arn,
        external_id=_safe_decrypt(current_user, "external_id", db),
    )


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------

@router.put("/profile", response_model=UserResponse)
def update_profile(
    request_data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request_data.email and request_data.email != current_user.email:
        existing = db.query(User).filter(User.email == request_data.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        current_user.email = request_data.email
    if request_data.full_name is not None:
        current_user.full_name = request_data.full_name
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/password")
def change_password(
    request: Request,
    request_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    auth_token: Optional[str] = Cookie(default=None),
):
    if not verify_password(request_data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(request_data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    current_user.password_hash = get_password_hash(request_data.new_password)
    db.commit()

    header_value = request.headers.get("Authorization", "")
    raw_token = header_value.removeprefix("Bearer ").strip() if header_value.startswith("Bearer ") else auth_token
    payload = decode_access_token(raw_token) if raw_token else None
    if payload and payload.get("jti") and payload.get("exp"):
        from datetime import timezone
        revoke_token(
            jti=payload["jti"],
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            db=db,
        )

    _write_audit(db, "password_change", user_id=current_user.id,
                 ip=request.client.host if request.client else None)
    return {"message": "Password updated successfully"}


# ---------------------------------------------------------------------------
# Environment variables (Anthropic API key)
# ---------------------------------------------------------------------------

@router.get("/env-vars", response_model=EnvVarsResponse)
def get_env_vars(current_user: User = Depends(get_current_user)):
    key_set = bool(current_user.anthropic_api_key)
    preview = None
    if key_set:
        try:
            decrypted = decrypt_aws_credentials(
                current_user.anthropic_api_key, user_salt=current_user.credential_salt
            )
            preview = "sk-ant-****" + decrypted[-4:] if len(decrypted) > 4 else "****"
        except Exception:
            preview = "****"
    return EnvVarsResponse(anthropic_api_key_set=key_set, anthropic_api_key_preview=preview)


@router.put("/env-vars", response_model=EnvVarsResponse)
def update_env_vars(
    request: Request,
    env_request: EnvVarsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.credential_salt:
        current_user.credential_salt = generate_credential_salt()

    if not env_request.anthropic_api_key:
        current_user.anthropic_api_key = None
    else:
        current_user.anthropic_api_key = encrypt_aws_credentials(
            env_request.anthropic_api_key, user_salt=current_user.credential_salt
        )
    db.commit()
    db.refresh(current_user)

    key_set = bool(current_user.anthropic_api_key)
    preview = None
    if key_set:
        try:
            decrypted = decrypt_aws_credentials(
                current_user.anthropic_api_key, user_salt=current_user.credential_salt
            )
            preview = "sk-ant-****" + decrypted[-4:] if len(decrypted) > 4 else "****"
        except Exception:
            preview = "****"

    _write_audit(db, "env_vars_update", user_id=current_user.id,
                 ip=request.client.host if request.client else None)
    return EnvVarsResponse(anthropic_api_key_set=key_set, anthropic_api_key_preview=preview)


@router.get("/platform-info")
def platform_info(_: User = Depends(get_current_user)):
    return {"cloudkraft_iam_arn": settings.CLOUDKRAFT_IAM_ARN}
