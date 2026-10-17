from sqlalchemy import text

from app.db import get_engine


def garantir_usuario(telefone: str) -> bool:
    """Cadastra o usuário (com conta individual) se for a primeira mensagem.

    Devolve True se o usuário ou a conta acabou de ser criado. Quem ainda é só um pedido de
    acesso (registrar_pendente) tem usuário, mas não conta; a conta nasce aqui, depois da liberação.
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
            user_id = connection.execute(
                text("SELECT id FROM users WHERE phone_number = :telefone"), {"telefone": telefone}
            ).scalar_one()
            tem_conta = connection.execute(
                text("SELECT 1 FROM members WHERE user_id = :user_id LIMIT 1"), {"user_id": user_id}
            ).first()
            if tem_conta:
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


def conta_do_usuario(telefone: str) -> tuple[str, str]:
    """Devolve (user_id, account_id) da conta mais recente em que o usuário está."""
    with get_engine().connect() as connection:
        linha = connection.execute(
            text(
                "SELECT u.id AS user_id, m.account_id FROM users u"
                " JOIN members m ON m.user_id = u.id"
                " WHERE u.phone_number = :telefone"
                " ORDER BY m.joined_at DESC LIMIT 1"
            ),
            {"telefone": telefone},
        ).one()
    return linha.user_id, linha.account_id
