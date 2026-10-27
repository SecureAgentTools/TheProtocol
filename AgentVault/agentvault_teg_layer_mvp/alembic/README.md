# Alembic Database Migrations for TEG Layer MVP

This directory contains database migration scripts managed by Alembic.

## Initial Setup

1. **Ensure PostgreSQL is running and database is created:**
   ```sql
   CREATE DATABASE teg_db;
   CREATE USER teg_user WITH PASSWORD 'teg_pass';
   GRANT ALL PRIVILEGES ON DATABASE teg_db TO teg_user;
   ```

2. **Configure database URL:**
   - Edit `.env` file in the parent directory
   - Set `DATABASE_URL=postgresql://teg_user:teg_pass@localhost:5432/teg_db`
   - OR for testing: `DATABASE_URL=sqlite:///./teg_database.db`

3. **Run initial migration:**
   ```bash
   # From the agentvault_teg_layer_mvp directory
   alembic upgrade head
   ```

## Common Commands

- **Check current version:**
  ```bash
  alembic current
  ```

- **Show migration history:**
  ```bash
  alembic history
  ```

- **Create new migration (auto-generate):**
  ```bash
  alembic revision --autogenerate -m "Description of changes"
  ```

- **Create new migration (manual):**
  ```bash
  alembic revision -m "Description of changes"
  ```

- **Upgrade to latest:**
  ```bash
  alembic upgrade head
  ```

- **Downgrade one version:**
  ```bash
  alembic downgrade -1
  ```

- **Show SQL without executing:**
  ```bash
  alembic upgrade head --sql
  ```

## Files

- `env.py` - Alembic environment configuration
- `script.py.mako` - Template for new migration files
- `versions/` - Directory containing migration scripts
- `versions/001_initial_schema.py` - Initial database schema

## Troubleshooting

1. **"Can't find module" errors:**
   - Ensure you're running alembic from the `agentvault_teg_layer_mvp` directory
   - Activate the poetry virtual environment: `poetry shell`

2. **Database connection errors:**
   - Check PostgreSQL is running: `pg_isready`
   - Verify credentials in `.env` file
   - Test connection: `psql -U teg_user -d teg_db`

3. **Migration conflicts:**
   - Check current version: `alembic current`
   - Review history: `alembic history`
   - Force to specific version: `alembic stamp <revision>`

## Production Deployment

For production, include migration in your deployment process:

```bash
# In Dockerfile or deployment script
alembic upgrade head && uvicorn src.teg_core_service.main:app
```

Or use the provided Makefile:
```bash
make migrate
make run
```
