from sqlalchemy import text

from app.comandos.cadastro import conta_do_usuario
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import eh_nao, eh_sim, normalizar
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "apagar"
BOTOES = ("Apagar tudo", "Cancelar")

TEXTO_PRIVACIDADE = (
    "🔒 Seus dados ficam num banco protegido por senha e servem só para gerar seus resumos. "
    "Não vendo nem compartilho com ninguém. O acesso técnico ao banco é só do responsável pelo projeto, "
    "que não olha seus dados a não ser que você peça ajuda. No casal, seu parceiro só vê o que for conjunto. "
    "Para apagar tudo, mande /apagar_meus_dados."
)

TEXTO_APAGADO = (
    "Pronto, apaguei seus registros, metas, categorias, renda e nome. "
    "Mantive só seu número e a liberação de acesso, para você poder voltar quando quiser (/inicio)."
)


def comando_privacidade(argumentos: str) -> str:
    return TEXTO_PRIVACIDADE


def comando_apagar(telefone: str, argumentos: str) -> str | Resposta:
    salvar_estado(telefone, ESTADO, {})
    return Resposta(
        "Isso apaga TODOS os seus registros, metas, categorias, renda e nome. "
        "Não dá para desfazer. Apagar?",
        BOTOES,
    )


def _apagar(telefone: str, user_id, account_id) -> bool:
    """Apaga os dados do usuário. Devolve False se a conta tem mais de um membro."""
    with get_engine().begin() as connection:
        membros = connection.execute(
            text("SELECT count(*) FROM members WHERE account_id = :conta"),
            {"conta": account_id},
        ).scalar_one()
        if membros > 1:
            return False
        parametros = {"conta": account_id, "usuario": user_id, "telefone": telefone}
        for comando in (
            "DELETE FROM transactions WHERE account_id = :conta",
            "DELETE FROM recurring_transactions WHERE account_id = :conta",
            "DELETE FROM classification_rules WHERE account_id = :conta",
            "DELETE FROM savings_goals WHERE account_id = :conta",
            "DELETE FROM installments WHERE account_id = :conta",
            "DELETE FROM goals WHERE account_id = :conta",
            "DELETE FROM sent_alerts WHERE account_id = :conta",
            "DELETE FROM categories WHERE account_id = :conta",
            "UPDATE members SET expected_income = NULL"
            " WHERE account_id = :conta AND user_id = :usuario",
            "UPDATE users SET display_name = NULL, cadastro_completo = FALSE WHERE id = :usuario",
            "DELETE FROM processed_messages WHERE sender_phone_number = :telefone",
        ):
            connection.execute(text(comando), parametros)
    return True


def continuar_apagar(telefone: str, dados: dict, texto: str) -> str | Resposta:
    if eh_nao(texto):
        limpar_estado(telefone)
        return "Certo, não apaguei nada."
    if not (eh_sim(texto) or normalizar(texto).strip(" .!") in ("apagar tudo", "apagar")):
        return Resposta("Toque em Apagar tudo ou Cancelar.", BOTOES)
    user_id, account_id = conta_do_usuario(telefone)
    apagou = _apagar(telefone, user_id, account_id)
    limpar_estado(telefone)
    if not apagou:
        return "Sua conta é compartilhada e ainda não sei apagar só a sua parte. Nada foi apagado. Se quiser, mande /sair_casal primeiro."
    return TEXTO_APAGADO
