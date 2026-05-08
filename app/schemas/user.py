from pydantic import BaseModel, EmailStr
from typing import Literal, Optional
from datetime import datetime


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserAWSRegister(BaseModel):
    email: EmailStr
    full_name: str
    aws_access_key: str
    aws_secret_key: str
    aws_region: str


class ConnectAWSRequest(BaseModel):
    auth_method: Literal["access_key", "assume_role"]
    region: str
    # access_key fields
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    # assume_role fields
    role_arn: Optional[str] = None
    external_id: Optional[str] = None


class AWSStatusResponse(BaseModel):
    connected: bool
    auth_method: Optional[str] = None
    region: Optional[str] = None
    role_arn: Optional[str] = None
    external_id: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class EnvVarsRequest(BaseModel):
    anthropic_api_key: Optional[str] = None


class EnvVarsResponse(BaseModel):
    anthropic_api_key_set: bool
    anthropic_api_key_preview: Optional[str] = None  # last 4 chars masked


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None

