from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import timedelta, datetime, timezone
import secrets
from dotenv import load_dotenv

from database import get_db
from models import User
from schemas import Token
import os

load_dotenv()
pwd_context = CryptContext(schemes=['sha256_crypt'], deprecated='auto')

SECRET_KEY = os.getenv('SECRET_KEY')
ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    verified = pwd_context.verify(plain_password, hashed_password)
    return verified

def hash_password(password: str) -> str:
    hashed = pwd_context.hash(password)
    return hashed


def create_token(data: dict, expires_delta: timedelta | None = None) -> str:
    
    if not expires_delta:
        time = datetime.now(timezone.utc) + timedelta(ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        time = datetime.now(timezone.utc) + expires_delta

    data['exp'] = time
    token = jwt.encode(claims=data, key=SECRET_KEY, algorithm=ALGORITHM)
    return token

async def decode_token(token: str, db = AsyncSession) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},)
    try:
        payload = jwt.decode(token=token, key=SECRET_KEY, algorithms=ALGORITHM)

        username: str = payload.get('username')
        if username is None:
            raise credentials_exception
    
    except JWTError:
        raise credentials_exception
    
    user = await db.execute(select(User).filter_by(username=username, is_active=True))
    user = user.scalar_one_or_none()

    if user is None:
        raise credentials_exception
    return user

    




async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(token=token, algorithms=ALGORITHM, key=SECRET_KEY)
        username: str = payload.get('username')
        
        if username is None:
            raise credentials_exception
    
    except JWTError:
        raise credentials_exception
    
    user_result = await db.execute(select(User).filter_by(username=username, is_active=True))
    user = user_result.scalar_one_or_none()
    if not user:
        raise credentials_exception 
    return user




        
        

