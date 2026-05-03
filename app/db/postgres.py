from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

settings = get_settings()
# Convert postgresql:// to postgresql+psycopg:// for psycopg v3 driver
postgres_dsn = settings.postgres_dsn.replace("postgresql://", "postgresql+psycopg://")
engine = create_engine(postgres_dsn, echo=False)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

