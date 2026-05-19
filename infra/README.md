# Infrastructure Notes

This folder contains local infrastructure scaffolding for MedVoice Scheduler.

## PostgreSQL
- Image: `pgvector/pgvector:pg16`
- Init scripts: `infra/postgres/init/`
- Persistent volume: `postgres_data`

## Planned Additions
- Migration pipeline
- Backup/restore scripts
- Observability stack
