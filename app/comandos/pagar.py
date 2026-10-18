"""/pagar (e /parcelas pagar): paga a próxima parcela de uma compra parcelada."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app import financas
from app.comandos.cadastro import conta_do_usuario
from app.comandos.categorias import chave, listar_categorias
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import eh_nao, eh_sim, formatar_reais
from app.comandos.objetivos import ARTIGOS
from app.comandos.parcelas import listar_parcelas
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "pagar"
PREFIXO = "pag:"  # id das linhas da lista
BOTOES = ("Sim", "Cancelar")
CATEGORIA = "Parcelas/dívidas"
MAX_BOTOES = 3
MAX_LISTA = 10


def numero_da_parcela(p: financas.Parcelamento, hoje: date) -> int:
    return min(p.pagas(hoje) + 1, p.total)


def a_pagar_no_mes(parcelas: list[financas.Parcelamento], hoje: date) -> list[financas.Parcelamento]:
    """Parcelas com pagamento pendente até o fim do mês, da que vence primeiro para a última."""
    return sorted(
        (p for p in parcelas if p.pendente_no_mes(hoje)), key=lambda p: p.proximo_vencimento(hoje)
    )


def achar_por_nome(parcelas: list[financas.Parcelamento], nome: str) -> list[financas.Parcelamento]:
    """Parcelas cujo nome é o procurado (igual, ou um contido no outro), sem acento nem maiúsculas."""
    procurado = " ".join(w for w in chave(nome).split() if w not in ARTIGOS)
    if not procurado:
        return []
    exatas = [p for p in parcelas if chave(p.nome) == procurado]
    if exatas:
        return exatas
    return [p for p in parcelas if procurado in chave(p.nome) or chave(p.nome) in procurado]


def _resumo(p: financas.Parcelamento, hoje: date) -> str:
    return (f"{numero_da_parcela(p, hoje)}/{p.total} de {formatar_reais(p.valor)}"
            f" · vence {p.proximo_vencimento(hoje):%d/%m}")


def _escolher(telefone: str, abertas: list[financas.Parcelamento], hoje: date, aviso: str = "") -> str | Resposta:
    """Botões (até 3) ou lista (até 10) para escolher qual parcela pagar."""
    if not abertas:
        return f"{aviso}Nenhuma parcela para pagar neste mês."
    mostradas = abertas[:MAX_LISTA]
    salvar_estado(telefone, ESTADO, {"etapa": "escolher", "ids": [p.id for p in mostradas]})
    texto = f"{aviso}Qual parcela você pagou?"
    if len(abertas) > MAX_LISTA:
        texto += f"\nMostrando as {MAX_LISTA} mais próximas do vencimento, de {len(abertas)}."
    if len(abertas) <= MAX_BOTOES:
        linhas = "\n".join(f"• {p.nome}: {_resumo(p, hoje)}" for p in mostradas)
        return Resposta(f"{texto}\n{linhas}", tuple(p.nome[:20] for p in mostradas))
    linhas = tuple((PREFIXO + p.id, p.nome[:24], _resumo(p, hoje)[:72]) for p in mostradas)
    return Resposta(texto, lista=linhas, botao_lista="Escolher", titulo_lista="Parcelas")


def _confirmar(telefone: str, p: financas.Parcelamento, hoje: date) -> str | Resposta:
    """Confere se há parcela a pagar neste mês e pede o Sim. Nada é salvo aqui."""
    if p.restantes(hoje) == 0:
        return f"{p.nome} já está quitada. 🎉"
    if not p.pendente_no_mes(hoje):
        return (f"A parcela deste mês de {p.nome} já está paga. "
                f"A próxima é a {numero_da_parcela(p, hoje)}/{p.total}, vence {p.proximo_vencimento(hoje):%d/%m/%Y}.")
    salvar_estado(telefone, ESTADO, {"etapa": "confirmar", "id": p.id, "esperado": p.pagas(hoje)})
    return Resposta(f"{p.nome}, parcela {numero_da_parcela(p, hoje)}/{p.total}, {formatar_reais(p.valor)}. Confirmar?", BOTOES)


def comando_pagar(telefone: str, argumentos: str) -> str | Resposta:
    hoje = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    parcelas = listar_parcelas(account_id, user_id)
    nome = argumentos.strip()
    aviso = ""
    if nome:
        achadas = achar_por_nome(parcelas, nome)
        if len(achadas) == 1:
            return _confirmar(telefone, achadas[0], hoje)
        if achadas:
            abertas = a_pagar_no_mes(achadas, hoje)
            if len(abertas) == 1:
                return _confirmar(telefone, abertas[0], hoje)
            if not abertas:
                return f"As parcelas de \"{nome}\" já estão pagas neste mês."
            return _escolher(telefone, abertas, hoje)
        aviso = f"Não achei nenhuma parcela chamada \"{nome}\".\n"
    return _escolher(telefone, a_pagar_no_mes(parcelas, hoje), hoje, aviso)


# ---------- banco de dados ----------

def _id_da_categoria(account_id) -> str | None:
    return next((c.id for c in listar_categorias(account_id) if chave(c.nome) == chave(CATEGORIA)), None)


def registrar_pagamento(account_id, user_id, parcela_id: str, esperado: int, hoje: date) -> tuple[str, int] | None:
    """Grava a saída e marca a parcela como paga, tudo ou nada.

    Devolve (nome, número pago, total) ou None se a parcela mudou (ex.: já foi paga).
    """
    categoria = _id_da_categoria(account_id)
    transacao = str(uuid.uuid4())
    with get_engine().begin() as connection:
        parcela = connection.execute(
            text("SELECT description, installment_amount, total_installments, scope"
                 " FROM installments WHERE id = :id AND account_id = :conta"),
            {"id": parcela_id, "conta": account_id},
        ).first()
        if parcela is None or esperado >= parcela.total_installments:
            return None
        marcada = connection.execute(
            text("UPDATE installments SET paid_installments = :novo, last_payment_id = :transacao"
                 " WHERE id = :id AND account_id = :conta"
                 " AND COALESCE(paid_installments, :esperado) = :esperado"),
            {"novo": esperado + 1, "transacao": transacao, "id": parcela_id,
             "conta": account_id, "esperado": esperado},
        ).rowcount
        if not marcada:
            return None  # outra confirmação chegou primeiro: não registra de novo
        numero = esperado + 1
        connection.execute(
            text("INSERT INTO transactions (id, account_id, created_by_user_id, category_id,"
                 " transaction_type, amount, description, payee, transaction_date, scope, source)"
                 " VALUES (:id, :conta, :usuario, :categoria, 'expense', :valor, :descricao,"
                 " :favorecido, :data, :escopo, 'manual')"),
            {"id": transacao, "conta": account_id, "usuario": user_id, "categoria": categoria,
             "valor": Decimal(str(parcela.installment_amount)),
             "descricao": f"{parcela.description} (parcela {numero}/{parcela.total_installments})",
             "favorecido": parcela.description, "data": hoje, "escopo": parcela.scope},
        )
    return parcela.description, numero, parcela.total_installments


def continuar_pagar(telefone: str, dados: dict, texto: str) -> str | Resposta | None:
    """Escolha da parcela -> [Sim] [Cancelar]. None (e esquece a conversa) se não for resposta esperada."""
    hoje = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    parcelas = listar_parcelas(account_id, user_id)
    if dados["etapa"] == "escolher":
        candidatas = [p for p in parcelas if p.id in dados["ids"]]
        alvo = next((p for p in candidatas if texto == PREFIXO + p.id), None) or next(
            (p for p in candidatas if chave(p.nome[:20]) == chave(texto)), None)
        if alvo is None:
            limpar_estado(telefone)
            return None
        return _confirmar(telefone, alvo, hoje)
    # etapa "confirmar"
    if eh_nao(texto):
        limpar_estado(telefone)
        return "Certo, não registrei o pagamento."
    if not eh_sim(texto):
        return Resposta("Responda Sim ou Cancelar.", BOTOES)
    limpar_estado(telefone)
    p = next((x for x in parcelas if x.id == dados["id"]), None)
    if p is None:
        return "Essa parcela já não existe."
    if p.pagas(hoje) != dados["esperado"] or not p.pendente_no_mes(hoje):
        return f"A parcela deste mês de {p.nome} já está paga. Não registrei de novo."
    pago = registrar_pagamento(account_id, user_id, p.id, dados["esperado"], hoje)
    if pago is None:
        return f"A parcela deste mês de {p.nome} já está paga. Não registrei de novo."
    nome, numero, total = pago
    resposta = f"Anotado: {nome}, parcela {numero}/{total}, {formatar_reais(p.valor)} em {CATEGORIA}."
    if numero == total:
        return f"{resposta}\nÚltima parcela paga: a dívida {nome} está quitada! 🎉"
    return f"{resposta}\nFaltam {total - numero}."
