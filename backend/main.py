import asyncio
import json
import os
from fastapi import FastAPI, Depends
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import init_db, get_session
from models import Account, Channel, Message
import redis.asyncio as redis

app = FastAPI(title="TG Parser System")
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://redis"))

# --- API ENDPOINTS ---

@app.on_event("startup")
async def on_startup():
    await init_db()
    # Запуск фоновых задач
    asyncio.create_task(dispatcher_loop())
    asyncio.create_task(ingestor_loop())

@app.post("/accounts/")
async def add_account(account: Account, session: AsyncSession = Depends(get_session)):
    session.add(account)
    await session.commit()
    return {"status": "ok", "account": account.phone}

@app.post("/channels/")
async def add_channel(channel: Channel, session: AsyncSession = Depends(get_session)):
    session.add(channel)
    await session.commit()
    return {"status": "ok", "channel": channel.username}

@app.get("/stats/")
async def get_stats(session: AsyncSession = Depends(get_session)):
    # Простая статистика
    msgs = await session.execute(select(Message))
    return {"total_messages": len(msgs.scalars().all())}

# --- DISPATCHER (Раздает задачи) ---

async def dispatcher_loop():
    """Ищет каналы для парсинга и свободные аккаунты"""
    async for db in get_session(): # Получаем сессию вручную
        while True:
            try:
                # 1. Найти свободный аккаунт
                acc_res = await db.execute(select(Account).where(Account.is_active == True))
                account = acc_res.scalars().first()
                
                # 2. Найти канал, который нужно парсить
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
                    await redis_client.lpush("tasks_queue", json.dumps(task))
                    
                    # Обновляем статус канала
                    channel.status = "PARSING"
                    db.add(channel)
                    await db.commit()
                    print(f"[Dispatcher] Task sent for {channel.username}")
                
            except Exception as e:
                print(f"[Dispatcher Error] {e}")
            
            await asyncio.sleep(5) # Пауза между проверками

# --- INGESTOR (Сохраняет данные) ---

async def ingestor_loop():
    """Читает результаты из Redis и пишет в Postgres"""
    async for db in get_session():
        while True:
            try:
                # Блокирующее чтение из очереди результатов (ждем 1 сек)
                data = await redis_client.brpop("results_queue", timeout=1)
                if data:
                    _, raw_json = data
                    result = json.loads(raw_json)
                    
                    if result.get("status") == "done":
                        # Обновляем статус канала
                        chan_res = await db.execute(select(Channel).where(Channel.username == result["channel"]))
                        channel = chan_res.scalars().first()
                        if channel:
                            channel.status = "DONE"
                            channel.last_parsed_id = result["max_id"]
                            db.add(channel)
                    
                    elif result.get("type") == "message":
                        # Сохраняем сообщение
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