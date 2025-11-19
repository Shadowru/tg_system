Distributed Telegram Parser System

A scalable, microservices-based system for scraping Telegram channel history and messages. It features a web dashboard for management, a distributed worker architecture for high throughput, and a full monitoring stack.


##🚀 Features

Web Dashboard: Manage Telegram accounts (sessions) and target channels via a user-friendly UI.
Distributed Architecture: Workers can run on different servers/VPS to scale parsing and avoid IP bans.
Asynchronous Core: Built with FastAPI and Telethon for high performance.
Smart Dispatcher: Automatically distributes tasks to available accounts using a Redis Queue.
Bulk Ingestion: Dedicated service to buffer and insert data into PostgreSQL efficiently.
Full Monitoring: Integrated Prometheus and Grafana for tracking queue depth, API load, and worker health.

🏗 Architecture

The system consists of several decoupled components:

Control Plane (Backend): FastAPI app that serves the Dashboard, manages the Database, and runs the Dispatcher (creates tasks) and Ingestor (saves results).
Message Broker (Redis): Handles communication between the Control Plane and Workers (
tasks_queue
and
results_queue
).
Workers: Stateless Python scripts running Telethon. They fetch tasks from Redis, connect to Telegram, scrape data, and push results back to Redis.
Storage: PostgreSQL for persistent data (accounts, channels, messages).
Monitoring: Prometheus scrapes metrics; Grafana visualizes them; Redis Exporter monitors queue sizes.

🛠 Prerequisites

Docker and Docker Compose installed.
Telegram API Credentials (
api_id
and
api_hash
) obtained from 
my.telegram.org
.

📦 Installation & Setup

1. Clone the Repository

git clone https://github.com/yourusername/tg-parser-system.git
cd tg-parser-system
bash


2. Generate a Telegram Session String

The system uses Telethon 
StringSession
 to log in without interactive prompts. Run this Python script locally to generate your session string:

# save this as gen_session.py and run it
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = 123456  # YOUR API ID
api_hash = 'your_api_hash'

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("Session String (Copy this):")
    print(client.session.save())
python


3. Start the System

Run the entire stack using Docker Compose:

docker-compose up --build -d

🖥 Usage

Web Dashboard

Open your browser and navigate to: 
http://localhost:8000


Add an Account:

Click "Add" in the Accounts section.
Enter your Phone Number, API ID, API Hash, and the Session String generated in step 2.
(Optional) Add a Proxy URL (
socks5://user:pass@host:port
).
Add a Channel:

Click "Add" in the Channels section.
Enter the username (e.g.,
python_scripts
without
@
).
Watch it work:

The Dispatcher will pick up the pending channel.
A Worker will process it.
The status will change to
PARSING
and then
DONE
.
The "Total Messages" counter will increase.

API Documentation

Full Swagger UI is available at: 
http://localhost:8000/docs


📊 Monitoring

The system comes with a pre-configured monitoring stack.


Grafana:
http://localhost:3000
(Default login:
admin
/
admin
)
Prometheus:
http://localhost:9090

Key Metrics to Watch:

Redis Queue Depth: If
tasks_queue
is high, add more workers. If
results_queue
is high, the database is the bottleneck.
Backend RPS: Requests per second to the API.

🌐 Scaling (Running Workers Remotely)

To run workers on a different server (e.g., a cheap VPS to rotate IPs):

Ensure port 6379 (Redis) on your main server is accessible (configure firewall and Redis password!).
Copy the
worker/
folder to the remote server.
Run the worker container manually or via a separate
docker-compose.yml
:

version: '3.8'
services:
  worker:
    build: .
    environment:
      # Point to your Main Server IP
      - BROKER_URL=redis://user:password@MAIN_SERVER_IP:6379
    restart: always
yaml


📂 Project Structure

.
├── docker-compose.yml      # Orchestration
├── prometheus.yml          # Monitoring config
├── backend/                # API, Dashboard, Dispatcher, Ingestor
│   ├── main.py
│   ├── models.py
│   ├── templates/          # HTML Jinja2 Templates
│   └── ...
└── worker/                 # Parsing Logic
    ├── worker.py

text


📄 License

This project is licensed under the MIT License.



Disclaimer: This tool is for educational purposes. Please respect Telegram's Terms of Service and API usage limits.