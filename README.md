# Distributed Encrypted Chat - Stage 2 (Multi-Server)

## Overview
Stage 2 evolves the chat backend from a single instance into a horizontally scaled, distributed system. Multiple FastAPI instances run concurrently behind an Nginx load balancer. 

Because active WebSockets are stateful and live in local server memory, **Redis Pub/Sub** acts as the high-speed communication bus. It instantly routes real-time events between servers so that a sender on Server 1 can seamlessly chat with a recipient on Server 3.

## Architecture
- **Load Balancer:** Nginx (Round-robin traffic distribution)
- **API Framework:** 3x FastAPI (Python 3.11+) Nodes
- **Real-Time Communication:** Redis Pub/Sub (`redis.asyncio`)
- **Persistent Storage:** PostgreSQL (Shared Database)
- **Design Pattern:** "Persist Before Publish" — messages are durably stored in PostgreSQL before being published to the transient Redis real-time layer.

## How to Run (Docker)
1. Ensure Docker Desktop is running.
2. Copy `.env.example` to `.env`.
3. Spin up the entire infrastructure:
   ```bash
   docker compose up --build -d