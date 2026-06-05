# MedVoice Scheduler (POC)

POC monorepo scaffold for a voice-first medical scheduling system.

## Stack
- Backend: FastAPI (Python)
- Workflow: LangGraph
- MCP server: Python MCP server
- Database: PostgreSQL + pgvector
- Frontend: React + Vite
- Containerization: Docker + Docker Compose

## Repository Structure
- `backend/` - FastAPI service scaffold
- `frontend/` - React + Vite scaffold
- `mcp-server/` - Python MCP server scaffold
- `infra/postgres/` - PostgreSQL + pgvector bootstrap files
- `docs/` - project documentation

## Quick Start (Scaffold Only)
1. Copy `.env.example` to `.env`
2. Add your Gemini API key and voice model settings:
   - `GEMINI_API_KEY=...`
   - `GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview`
   - `GEMINI_LIVE_VOICE=Kore`
3. Build containers:
   - `docker compose build`
4. Start services:
   - `docker compose up -d`

## Voice Behavior
- Typed patient messages receive typed assistant replies.
- Spoken patient messages are recorded after `Start Voice`, sent to Gemini Live for transcription after `Stop Recording`, then the assistant reply is played with Gemini Live voice.
- Assistant messages can also be replayed with the `Play` button.
- Patients can use the `Call center` button to start a browser call with a Vapi medical center assistant.
- Vapi setup instructions are in `docs/vapi-call-assistant.md`.

## Services (Planned)
- `frontend` -> React app
- `backend` -> FastAPI API
- `mcp-server` -> MCP tool server
- `postgres` -> PostgreSQL with pgvector

## Notes
- This repository currently contains only project structure and configuration.
- No business logic is implemented yet.

