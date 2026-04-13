"""
JWT Authentication module for AEGIS-FOOD marketplace.
Handles user registration, login, and token verification.
"""

from datetime import datetime, timedelta
from typing import Optional
import os
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
import database

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Pydantic models
class UserCreate(BaseModel):
    """User registration request"""
    email: EmailStr
    password: str
    empresa_id: int
    nombre_empresa: str
    rol: str = "user"  # 'user', 'admin'


class UserLogin(BaseModel):
    """User login request"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    """Token payload data"""
    email: Optional[str] = None
    empresa_id: Optional[int] = None
    rol: Optional[str] = None


class UserResponse(BaseModel):
    """User response model"""
    id: int
    email: str
    empresa_id: int
    nombre_empresa: str
    rol: str
    created_at: datetime

    class Config:
        from_attributes = True


# Password hashing utilities
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password"""
    return pwd_context.verify(plain_password, hashed_password)


# JWT token utilities
def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


def verify_token(token: str) -> TokenData:
    """Verify a JWT token and extract data"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        empresa_id: int = payload.get("empresa_id")
        rol: str = payload.get("rol")

        if email is None:
            raise JWTError("Invalid token")

        return TokenData(email=email, empresa_id=empresa_id, rol=rol)

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Dependency for getting current user from token
async def get_current_user(
    token: str,
    db: Session
) -> database.UserDB:
    """Get current authenticated user from token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        token_data = verify_token(token)
    except HTTPException:
        raise credentials_exception

    user = db.query(database.UserDB).filter(
        database.UserDB.email == token_data.email
    ).first()

    if user is None:
        raise credentials_exception

    return user


# User management functions
def create_user(
    db: Session,
    email: str,
    password: str,
    empresa_id: int,
    nombre_empresa: str,
    rol: str = "user"
) -> database.UserDB:
    """Create a new user in the database"""

    # Validate inputs
    if not email or len(email.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Email is required"
        )

    if not password or len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 6 characters"
        )

    if not nombre_empresa or len(nombre_empresa.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nombre empresa is required"
        )

    if empresa_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Valid empresa_id is required"
        )

    # Check if user already exists
    existing_user = db.query(database.UserDB).filter(
        database.UserDB.email == email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    hashed_password = hash_password(password)

    db_user = database.UserDB(
        email=email,
        hashed_password=hashed_password,
        empresa_id=empresa_id,
        nombre_empresa=nombre_empresa,
        rol=rol
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


def authenticate_user(
    db: Session,
    email: str,
    password: str
) -> Optional[database.UserDB]:
    """Authenticate a user with email and password"""

    user = db.query(database.UserDB).filter(
        database.UserDB.email == email
    ).first()

    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user
