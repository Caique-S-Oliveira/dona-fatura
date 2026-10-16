import json

from sqlalchemy import text

from app.db import get_engine

# Conversa abandonada há mais de 1 hora é esquecida.
VALIDADE = "1 hour"


def ler_estado(telefone: str) -> tuple[str, dict] | None:
    """Devolve (estado, dados) da conversa em andamento, ou None se não houver."""
    with get_engine().connect() as connection:
        linha = connection.execute(
            text(
                "SELECT state, data FROM conversation_state"
                " WHERE phone_number = :telefone"
                " AND (expires_at IS NULL OR expires_at > now())"
            ),
            {"telefone": telefone},
        ).first()
    if linha is None:
        return None
    return linha.state, linha.data


def salvar_estado(telefone: str, estado: str, dados: dict) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation_state (phone_number, state, data, expires_at)"
                f" VALUES (:telefone, :estado, CAST(:dados AS jsonb), now() + interval '{VALIDADE}')"
                " ON CONFLICT (phone_number) DO UPDATE SET state = EXCLUDED.state,"
                " data = EXCLUDED.data, expires_at = EXCLUDED.expires_at, updated_at = now()"
            ),
            {"telefone": telefone, "estado": estado, "dados": json.dumps(dados)},
        )


def limpar_estado(telefone: str) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text("DELETE FROM conversation_state WHERE phone_number = :telefone"),
            {"telefone": telefone},
        )
