import os
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

load_dotenv()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("A variável DATABASE_URL não está definida.")

    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://", "postgresql+psycopg://", 1
        )
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )

    return create_engine(database_url, pool_pre_ping=True)


def test_connection() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    print("Conexão com o banco de dados estabelecida com sucesso.")


if __name__ == "__main__":
    test_connection()
