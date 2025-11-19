from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    phone: str
    api_id: int
    api_hash: str
    session_string: str  # Telethon StringSession
    is_active: bool = True
    proxy_url: Optional[str] = None

class Channel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True) # @username или ссылка
    status: str = "PENDING" # PENDING, PARSING, DONE, ERROR
    last_parsed_id: int = 0

class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_username: str
    telegram_id: int
    text: Optional[str] = None
    date: datetime
    # Составной уникальный ключ (channel + msg_id) нужно делать через SA args, 
    # но для MVP опустим.