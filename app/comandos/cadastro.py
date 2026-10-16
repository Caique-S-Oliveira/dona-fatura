from sqlalchemy import text

from app.db import get_engine


def garantir_usuario(telefone: str) -> bool:
    """Cadastra o usuário (com conta individual) se for a primeira mensagem.

    Devolve True se o usuário acabou de ser criado.
    """
    with get_engine().begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (phone_number) VALUES (:telefone)"
                " ON CONFLICT (phone_number) DO NOTHING RETURNING id"
            ),
            {"telefone": telefone},
        ).scalar()
        if user_id is None:
            return False  # já cadastrado
        account_id = connection.execute(
            text("INSERT INTO accounts (owner_user_id) VALUES (:user_id) RETURNING id"),
            {"user_id": user_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO members (account_id, user_id, role)"
                " VALUES (:account_id, :user_id, 'owner')"
            ),
            {"account_id": account_id, "user_id": user_id},
        )
        return True
