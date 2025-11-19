import asyncio
import json
import os
from datetime import datetime

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles # Если понадобятся статики, но пока не используем
from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis
from prometheus_fastapi_instrumentator import Instrumentator

from database import init_db, get_session
from models import Account, Channel, Message

# 1. Инициализация приложения
app = FastAPI(title="TG Parser System")

# 2. Настройка шаблонов
templates = Jinja2Templates(directory="templates")

# 3. Инициализация Redis (ГЛОБАЛЬНО)
# Получаем URL из переменных окружения (которые мы прописали в docker-compose из .env)
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise ValueError("REDIS_URL env variable is not set!")

# Создаем клиент. decode_responses=True позволяет получать строки вместо байтов
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Запуск метрик Prometheus
instrumentator = Instrumentator().instrument(app).expose(app)

# --- СОБЫТИЯ ЗАПУСКА ---

@app.on_event("startup")
async def startup():
    # Инициализация БД
    await init_db()
    
    # Запуск фоновых процессов
    asyncio.create_task(dispatcher_loop())
    asyncio.create_task(ingestor_loop())

# --- WEB UI ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    """Главная страница дэшборда"""
    
    # Получаем каналы
    channels_res = await session.execute(select(Channel).order_by(Channel.id.desc()))
    channels = channels_res.scalars().all()
    
    # Получаем аккаунты
    accounts_res = await session.execute(select(Account))
    accounts = accounts_res.scalars().all()
    
    # Считаем сообщения
    count_res = await session.execute(select(func.count()).select_from(Message))
    total_messages = count_res.scalar()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "channels": channels,
        "accounts": accounts,
        "total_messages": total_messages
    })

# --- API ENDPOINTS ---

@app.post("/accounts/")
async def add_account(account: Account, session: AsyncSession = Depends(get_session)):
    session.add(account)
    await session.commit()
    return {"status": "ok", "account": account.phone}

@app.delete("/accounts/{account_id}")
async def delete_account(account_id: int, session: AsyncSession = Depends(get_session)):
    account = await session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    await session.delete(account)
    await session.commit()
    return {"status": "deleted", "id": account_id}

@app.post("/channels/")
async def add_channel(channel: Channel, session: AsyncSession = Depends(get_session)):
    # Проверка на дубликаты
    existing = await session.execute(select(Channel).where(Channel.username == channel.username))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Channel already exists")

    session.add(channel)
    await session.commit()
    return {"status": "ok", "channel": channel.username}

@app.delete("/channels/{channel_id}")
async def delete_channel(channel_id: int, session: AsyncSession = Depends(get_session)):
    channel = await session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    await session.delete(channel)
    await session.commit()
    return {"status": "deleted", "id": channel_id}

@app.get("/stats/")
async def get_stats(session: AsyncSession = Depends(get_session)):
    msgs = await session.execute(select(func.count()).select_from(Message))
    return {"total_messages": msgs.scalar()}

# --- BACKGROUND TASKS (DISPATCHER & INGESTOR) ---

async def dispatcher_loop():
    """Ищет каналы для парсинга и свободные аккаунты"""
    print("[Dispatcher] Started")
    # Используем отдельный генератор сессий, т.к. это фоновая задача
    async for db in get_session():
        while True:
            try:
                # 1. Найти свободный аккаунт
                acc_res = await db.execute(select(Account).where(Account.is_active == True))
                account = acc_res.scalars().first()
                
                # 2. Найти канал, который нужно парсить (PENDING)
                chan_res = await db.execute(select(Channel).where(Channel.status == "PENDING"))
                channel = chan_res.scalars().first()

                if account and channel:
                    # Формируем задачу
                    task = {
                        "type": "history",
                        "channel_username": channel.username,
                        "min_id": channel.last_parsed_id,
                        "session": account.session_string,
                        "api_id": account.api_id,
                        "api_hash": account.api_hash,
                        "proxy": account.proxy_url
                    }
                    
                    # Отправляем в очередь Redis
                    # json.dumps нужен, т.к. Redis хранит строки
                    await redis_client.lpush("tasks_queue", json.dumps(task))
                    
                    # Обновляем статус канала
                    channel.status = "PARSING"
                    db.add(channel)
                    await db.commit()
                    print(f"[Dispatcher] Task sent for {channel.username}")
                
            except Exception as e:
                print(f"[Dispatcher Error] {e}")
                # Если ошибка БД, пробуем откатить (хотя в asyncpg это авто)
                # await db.rollback()
            
            await asyncio.sleep(5) # Пауза между проверками

async def ingestor_loop():
    """Читает результаты из Redis и пишет в Postgres"""
    print("[Ingestor] Started")
    async for db in get_session():
        while True:
            try:
                # Блокирующее чтение из очереди результатов (ждем 1 сек)
                # brpop возвращает кортеж (имя_очереди, данные)
                data = await redis_client.brpop("results_queue", timeout=1)
                
                if data:
                    _, raw_json = data
                    result = json.loads(raw_json)
                    
                    if result.get("status") == "done":
                        # Обновляем статус канала на DONE
                        chan_res = await db.execute(select(Channel).where(Channel.username == result["channel"]))
                        channel = chan_res.scalars().first()
                        if channel:
                            channel.status = "DONE"
                            channel.last_parsed_id = result["max_id"]
                            db.add(channel)
                            print(f"[Ingestor] Channel {channel.username} DONE")
                    
                    elif result.get("type") == "message":
                        # Сохраняем сообщение
                        # Проверяем, нет ли уже такого сообщения (простая дедупликация)
                        # В реальном проде лучше использовать ON CONFLICT DO NOTHING на уровне SQL
                        msg = Message(
                            channel_username=result["channel"],
                            telegram_id=result["id"],
                            text=result["text"],
                            date=datetime.fromisoformat(result["date"])
                        )
                        db.add(msg)
                    
                    await db.commit()
            except Exception as e:
                print(f"[Ingestor Error] {e}")
                await asyncio.sleep(1)