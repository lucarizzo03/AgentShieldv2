# Migrations

This project uses Alembic with SQLModel metadata from `app/models`.

## Files

- `alembic.ini`
- `app/migrations/env.py`
- `app/migrations/script.py.mako`
- `app/migrations/versions/*.py`
- `scripts/migrate.py` (migration runner helper)

## Common Commands

```bash
# Apply all migrations
python3.11 scripts/migrate.py upgrade head

# Check current revision
python3.11 scripts/migrate.py current

# Create a new migration from model changes
python3.11 scripts/migrate.py revision --autogenerate --message "describe change"

# Roll back one revision
python3.11 scripts/migrate.py downgrade -1
```

## Notes

- `app/migrations/versions/0001_initial_schema.sql` is a legacy SQL snapshot.
- Alembic uses Python revision files as the source of migration history.

