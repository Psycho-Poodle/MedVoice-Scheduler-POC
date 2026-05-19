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
2. Build containers:
   - `docker compose build`
3. Start services:
   - `docker compose up -d`

## Services (Planned)
- `frontend` -> React app
- `backend` -> FastAPI API
- `mcp-server` -> MCP tool server
- `postgres` -> PostgreSQL with pgvector

## Notes
- This repository currently contains only project structure and configuration.
- No business logic is implemented yet.
- Refer to `PRD_MedVoice_Scheduler.md` for product requirements.

## Next Milestones
- API contract definitions
- LangGraph workflow skeleton
- MCP tool definitions
- DB schema and migration setup
- UI routes and shell layout
