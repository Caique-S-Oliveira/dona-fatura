from sqlalchemy import text

from app.comandos.cadastro import conta_do_usuario
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import eh_nao, eh_sim, formatar_reais
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "desfazer"
BOTOES = ("Sim", "Não")


def ultimo_registro(account_id, user_id):
    """Último registro feito por este usuário (outros membros da conta não entram)."""
    with get_engine().connect() as connection:
        return connection.execute(
            text(
                "SELECT t.id, t.transaction_type, t.amount, t.description,"
                " t.transaction_date, c.name AS categoria FROM transactions t"
                " LEFT JOIN categories c ON c.id = t.category_id"
                " WHERE t.account_id = :conta AND t.created_by_user_id = :usuario"
                " AND t.voided_at IS NULL"
                " ORDER BY t.created_at DESC LIMIT 1"
            ),
            {"conta": account_id, "usuario": user_id},
        ).first()


def descrever(registro) -> str:
    """"Gasto de R$ 45,90 — mercado (Mercado), 16/10/2026"."""
    tipo = "Gasto" if registro.transaction_type == "expense" else "Entrada"
    extra = f" ({registro.categoria})" if registro.categoria else ""
    data = registro.transaction_date.strftime("%d/%m/%Y")
    return f"{tipo} de {formatar_reais(registro.amount)} — {registro.description or '-'}{extra}, {data}"


def comando_desfazer(telefone: str, argumentos: str) -> str | Resposta:
    user_id, account_id = conta_do_usuario(telefone)
    registro = ultimo_registro(account_id, user_id)
    if registro is None:
        return "Você não tem nenhum registro para desfazer."
    salvar_estado(telefone, ESTADO, {"id": str(registro.id), "descricao": descrever(registro)})
    return Resposta(f"Apagar seu último registro?\n{descrever(registro)}", BOTOES)


def continuar_desfazer(telefone: str, dados: dict, texto: str) -> str | Resposta:
    if eh_nao(texto):
        limpar_estado(telefone)
        return "Certo, mantive o registro."
    if not eh_sim(texto):
        return Resposta(f"Responda Sim ou Não. Apagar?\n{dados['descricao']}", BOTOES)
    user_id, account_id = conta_do_usuario(telefone)
    with get_engine().begin() as connection:
        apagados = connection.execute(
            text(
                "DELETE FROM transactions WHERE id = :id"
                " AND account_id = :conta AND created_by_user_id = :usuario"
            ),
            {"id": dados["id"], "conta": account_id, "usuario": user_id},
        ).rowcount
    limpar_estado(telefone)
    if not apagados:
        return "Esse registro já não existe."
    return f"Pronto, apaguei: {dados['descricao']}."
