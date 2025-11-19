import asyncio
import json
import os
from fastapi import FastAPI, Depends
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import init_db, get_session
from models import Account, Channel, Message
import redis.asyncio as redis
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="TG Parser System")
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://redis"))

# --- API ENDPOINTS ---
#Instrumentator().instrument(app).expose(app)


@app.on_event("startup")
async def on_startup():
    await init_db()
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
    msgs = await session.execute(select(Message))
    return {"total_messages": len(msgs.scalars().all())}

# --- DISPATCHER ---

async def dispatcher_loop():
    async for db in get_session():
        while True:
            try:
                acc_res = await db.execute(select(Account).where(Account.is_active == True))
                account = acc_res.scalars().first()
                
                chan_res = await db.execute(select(Channel).where(Channel.status == "PENDING"))
                channel = chan_res.scalars().first()

                if account and channel:
                    task = {
                        "type": "history",
                        "channel_username": channel.username,
                        "min_id": channel.last_parsed_id,
                        "session": account.session_string,
                        "api_id": account.api_id,
                        "api_hash": account.api_hash,
                        "proxy": account.proxy_url
                    }
                    
                    await redis_client.lpush("tasks_queue", json.dumps(task))
                    
                    channel.status = "PARSING"
                    db.add(channel)
                    await db.commit()
                    print(f"[Dispatcher] Task sent for {channel.username}")
                
            except Exception as e:
                print(f"[Dispatcher Error] {e}")
            
            await asyncio.sleep(5)

# --- INGESTOR ---

async def ingestor_loop():
    async for db in get_session():
        while True:
            try:
                data = await redis_client.brpop("results_queue", timeout=1)
                if data:
                    _, raw_json = data
                    result = json.loads(raw_json)
                    
                    if result.get("status") == "done":
                        chan_res = await db.execute(select(Channel).where(Channel.username == result["channel"]))
                        channel = chan_res.scalars().first()
                        if channel:
                            channel.status = "DONE"
                            channel.last_parsed_id = result["max_id"]
                            db.add(channel)
                    
                    elif result.get("type") == "message":
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