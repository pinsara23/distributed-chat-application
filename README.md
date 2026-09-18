# Distributed Encrypted Chat - Stage 1

## Overview
This is Stage 1 of a 4-stage distributed chat architecture. Currently, it operates as a secure, single-server real-time chat backend. It features robust JWT authentication, asynchronous PostgreSQL persistence, and real-time bi-directional messaging via WebSockets.

## Architecture
- **API Framework:** FastAPI (Python 3.11+)
- **Database:** PostgreSQL (accessed asynchronously via `asyncpg`)
- **ORM:** SQLAlchemy 2.0 with strict Pydantic schema validation
- **Real-Time:** In-memory WebSocket connection manager (Single-server design)
- **Security:** Argon2id password hashing, JWT-based REST and WebSocket authentication

## Local Setup (Development)
1. **Database:** Ensure a local PostgreSQL instance is running with a database created (e.g., `chat_db`).
2. **Environment:** Copy `.env.example` to `.env` and fill in your database credentials and a secure `JWT_SECRET_KEY`.
3. **Dependencies:** 
   ```bash
   conda env create -f environment.yml
   conda activate chat-stage1