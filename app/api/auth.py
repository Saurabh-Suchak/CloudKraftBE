from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
import uuid
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, Token, UserAWSRegister, ConnectAWSRequest, AWSStatusResponse
from app.utils.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    encrypt_aws_credentials,
    decrypt_aws_credentials,
)
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user"""
    from app.utils.security import decode_access_token
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception
    
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    
    return user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        email=user_data.email,
        password_hash=hashed_password,
        full_name=user_data.full_name,
        external_id=encrypt_aws_credentials(str(uuid.uuid4())),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Login and get access token"""
    user = db.query(User).filter(User.email == form_data.username).first()
    
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/aws-register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_with_aws(user_data: UserAWSRegister, db: Session = Depends(get_db)):
    """Register a new user with AWS credentials"""
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Encrypt AWS credentials
    encrypted_access_key = encrypt_aws_credentials(user_data.aws_access_key)
    encrypted_secret_key = encrypt_aws_credentials(user_data.aws_secret_key)
    
    # Create new user
    db_user = User(
        email=user_data.email,
        password_hash=get_password_hash(""),  # Empty password for AWS-only users
        full_name=user_data.full_name,
        aws_access_key=encrypted_access_key,
        aws_secret_key=encrypted_secret_key,
        aws_region=user_data.aws_region,
        external_id=encrypt_aws_credentials(str(uuid.uuid4())),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user


@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user


@router.post("/connect-aws", response_model=AWSStatusResponse)
def connect_aws(
    request: ConnectAWSRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Attach or update AWS credentials for the logged-in user."""
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError

    if request.auth_method == "access_key":
        if not request.access_key or not request.secret_key:
            raise HTTPException(status_code=400, detail="access_key and secret_key required")

        # Validate credentials via STS
        try:
            sts = boto3.client(
                "sts",
                aws_access_key_id=request.access_key,
                aws_secret_access_key=request.secret_key,
                region_name=request.region,
            )
            sts.get_caller_identity()
        except (ClientError, NoCredentialsError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid AWS credentials: {e}")

        current_user.auth_method = "access_key"
        current_user.aws_access_key = encrypt_aws_credentials(request.access_key)
        current_user.aws_secret_key = encrypt_aws_credentials(request.secret_key)
        current_user.aws_region = request.region
        current_user.role_arn = None
        current_user.external_id = None

    elif request.auth_method == "assume_role":
        if not request.role_arn:
            raise HTTPException(status_code=400, detail="role_arn required for assume_role")

        # Validate by attempting to assume the role (requires backend AWS creds)
        if settings.BACKEND_AWS_ACCESS_KEY and settings.BACKEND_AWS_SECRET_KEY:
            try:
                sts = boto3.client(
                    "sts",
                    aws_access_key_id=settings.BACKEND_AWS_ACCESS_KEY,
                    aws_secret_access_key=settings.BACKEND_AWS_SECRET_KEY,
                    region_name=request.region or settings.BACKEND_AWS_REGION,
                )
                assume_params: dict = {
                    "RoleArn": request.role_arn,
                    "RoleSessionName": "cloudkraft-validation",
                }
                if request.external_id:
                    assume_params["ExternalId"] = request.external_id
                sts.assume_role(**assume_params)
            except (ClientError, NoCredentialsError) as e:
                raise HTTPException(status_code=400, detail=f"Could not assume role: {e}")

        current_user.auth_method = "assume_role"
        current_user.role_arn = request.role_arn
        current_user.external_id = (
            encrypt_aws_credentials(request.external_id) if request.external_id else None
        )
        current_user.aws_region = request.region
        current_user.aws_access_key = None
        current_user.aws_secret_key = None

    db.commit()

    return AWSStatusResponse(
        connected=True,
        auth_method=current_user.auth_method,
        region=current_user.aws_region,
        role_arn=current_user.role_arn,
    )


@router.get("/aws-status", response_model=AWSStatusResponse)
def aws_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return whether the user has AWS credentials connected."""
    # Backfill external_id for existing users that predate this field
    if not current_user.external_id:
        current_user.external_id = encrypt_aws_credentials(str(uuid.uuid4()))
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
        external_id=decrypt_aws_credentials(current_user.external_id),
    )

