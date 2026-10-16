import os
import secrets
from datetime import datetime

from sqlalchemy import text

from app.db import get_engine

MSG_PENDENTE = (
    "Oi! A Dona Fatura está em teste fechado.\n"
    "Se você recebeu um convite, mande /convite CÓDIGO."
)
MSG_INATIVO = (
    "Seu acesso à Dona Fatura não está ativo no momento.\n"
    "Fale com quem te convidou, por favor."
)


def so_digitos(telefone: str) -> str:
    """"+55 (11) 99999-8888" -> "5511999998888" (formato que o WhatsApp envia)."""
    return "".join(c for c in telefone if c.isdigit())


def eh_admin(telefone: str) -> bool:
    admin = so_digitos(os.getenv("ADMIN_NUMERO", ""))
    return bool(admin) and so_digitos(telefone) == admin


def codigo_convite_valido(codigo: str) -> bool:
    esperado = os.getenv("CODIGO_CONVITE", "").strip()
    return bool(esperado) and secrets.compare_digest(codigo.strip(), esperado)


def status_acesso(telefone: str) -> str:
    """Devolve "ativo", "pendente" ou "bloqueado" (acesso vencido conta como "bloqueado")."""
    with get_engine().connect() as connection:
        linha = connection.execute(
            text(
                "SELECT access_status, access_expires_at <= now() AS vencido"
                " FROM users WHERE phone_number = :telefone"
            ),
            {"telefone": telefone},
        ).first()
    if linha is None:
        return "pendente"
    if linha.access_status == "ativo" and linha.vencido:
        return "bloqueado"
    return linha.access_status


def _mudar_status(telefone: str, status: str, validade: datetime | None) -> bool:
    with get_engine().begin() as connection:
        resultado = connection.execute(
            text(
                "UPDATE users SET access_status = :status, access_expires_at = :validade"
                " WHERE phone_number = :telefone"
            ),
            {"status": status, "validade": validade, "telefone": so_digitos(telefone)},
        )
        return resultado.rowcount > 0


def liberar_acesso(telefone: str, validade: datetime | None = None) -> bool:
    """Deixa o usuário ativo até `validade` (None = sem data de fim).

    Usada pelo /convite, pelo /liberar e, no futuro, pela confirmação de pagamento.
    Devolve False se o número ainda não estiver cadastrado.
    """
    return _mudar_status(telefone, "ativo", validade)


def bloquear_acesso(telefone: str) -> bool:
    return _mudar_status(telefone, "bloqueado", None)


def comando_convite(telefone: str, argumentos: str) -> str:
    if not codigo_convite_valido(argumentos):
        return "Código inválido. Confira e tente de novo."
    liberar_acesso(telefone)
    return "Acesso liberado! Bem-vindo(a). Mande /ajuda para ver os comandos."


def comando_admin(nome: str, argumentos: str) -> str:
    numero = so_digitos(argumentos)
    if not numero:
        return f"Use: /{nome} NÚMERO (ex.: /{nome} 5511999998888)"
    acao = liberar_acesso if nome == "liberar" else bloquear_acesso
    if not acao(numero):
        return f"O número {numero} ainda não mandou mensagem para a Dona Fatura."
    return f"Número {numero} {'liberado' if nome == 'liberar' else 'bloqueado'}."
