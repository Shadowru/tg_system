from telethon.sync import TelegramClient
from telethon.sessions import StringSession
api_id = 12345
api_hash = 'your_hash'
with TelegramClient(StringSession(), api_id, api_hash) as client:
    print(client.session.save())