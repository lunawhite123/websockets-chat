from sqlalchemy import Column, String, Integer, DateTime, Boolean
from datetime import datetime, timezone
from database import Base

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True, index=True)
    room = Column(String, index=True)
    sender = Column(String, index=True)
    message = Column(String)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    


