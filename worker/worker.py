import os
import json
import asyncio
import redis.asyncio as redis
from telethon import TelegramClient
from telethon.sessions import StringSession

REDIS_URL = os.getenv("BROKER_URL", "redis://redis")
WORKER_ID = os.getenv("HOSTNAME", "worker-1")

async def process_task(task, redis_conn):
    print(f"[{WORKER_ID}] Processing {task['channel_username']}")
    
    # Инициализация клиента из строки сессии
    client = TelegramClient(
        StringSession(task['session']),
        task['api_id'],
        task['api_hash'],
        # proxy=... (добавить логику парсинга прокси строки)
    )

    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(f"[{WORKER_ID}] Session invalid")
            return

        channel = task['channel_username']
        min_id = task.get('min_id', 0)
        max_parsed_id = min_id

        # Парсинг истории
        async for msg in client.iter_messages(channel, limit=50, min_id=min_id):
            # Отправка сообщения в очередь результатов
            msg_data = {
                "type": "message",
                "channel": channel,
                "id": msg.id,
                "text": msg.text,
                "date": msg.date.isoformat()
            }
            await redis_conn.lpush("results_queue", json.dumps(msg_data))
            
            if msg.id > max_parsed_id:
                max_parsed_id = msg.id

        # Отчет о завершении
        done_msg = {
            "status": "done",
            "channel": channel,
            "max_id": max_parsed_id
        }
        await redis_conn.lpush("results_queue", json.dumps(done_msg))
        print(f"[{WORKER_ID}] Finished {channel}")

    except Exception as e:
        print(f"[{WORKER_ID}] Error: {e}")
    finally:
        await client.disconnect()

async def main():
    r = redis.from_url(REDIS_URL)
    print(f"[{WORKER_ID}] Started. Waiting for tasks...")
    
    while True:
        # Блокирующее ожидание задачи
        data = await r.brpop("tasks_queue", timeout=5)
        if data:
            _, raw_task = data
            task = json.loads(raw_task)
            await process_task(task, r)

if __name__ == "__main__":
    asyncio.run(main())