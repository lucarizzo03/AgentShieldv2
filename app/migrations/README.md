# Migrations

Use Alembic for schema migrations.

Suggested commands:

```bash
alembic init app/migrations
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

The SQLModel metadata is defined in `app/models`.

