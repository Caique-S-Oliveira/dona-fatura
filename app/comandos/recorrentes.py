"""Detecção de contas recorrentes: mesmo favorecido, valor parecido, em 2+ meses."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from app import financas
from app.comandos.cadastro import conta_do_usuario
from app.comandos.categorias import chave
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import eh_nao, eh_sim, formatar_reais
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "recorrente"
BOTOES = ("Sim", "Não")
TOLERANCIA = Decimal("0.10")  # valores até 10% diferentes contam como "parecidos"
MESES_MINIMOS = 2
DIAS_DE_HISTORICO = 190  # ~6 meses


@dataclass
class ContaRecorrente:
    id: str
    nome: str
    valor: Decimal
    frequencia: str
    proximo: date | None
    ativa: bool  # False = o usuário disse "não" (guardada só para não perguntar de novo)


# ---------- regras (sem banco) ----------

def parecido(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(a, b) * TOLERANCIA


def meses_parecidos(valor: Decimal, dia: date, historico: list[tuple[date, Decimal]]) -> int:
    """Em quantos meses diferentes houve um gasto de valor parecido (contando o de agora)."""
    meses = {(dia.year, dia.month)}
    meses.update((d.year, d.month) for d, v in historico if parecido(v, valor))
    return len(meses)


def proximo_mes(dia: date, dia_do_mes: int | None = None) -> date:
    """O mesmo dia no mês seguinte (31 vira o último dia do mês, se preciso)."""
    primeiro = financas.ultimo_dia_do_mes(dia) + timedelta(days=1)
    ultimo = financas.ultimo_dia_do_mes(primeiro).day
    return primeiro.replace(day=min(dia_do_mes or dia.day, ultimo))


def avancar_vencimento(proximo: date | None, pago_em: date) -> date | None:
    """Conta paga: o próximo vencimento passa para o mês seguinte ao pagamento."""
    if proximo is None or proximo > financas.ultimo_dia_do_mes(pago_em):
        return None  # já está num mês futuro: nada a mudar
    return proximo_mes(pago_em, proximo.day)


# ---------- banco de dados ----------

def contas_da_conta(account_id, user_id) -> list[ContaRecorrente]:
    """Contas recorrentes que o usuário pode ver (as "meu" do parceiro ficam de fora)."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT id, payee, amount, frequency, next_due_date, is_active"
                " FROM recurring_transactions WHERE account_id = :conta"
                " AND (scope = 'conjunto' OR created_by_user_id = :usuario)"
            ),
            {"conta": account_id, "usuario": user_id},
        ).all()
    return [ContaRecorrente(str(l.id), l.payee, l.amount, l.frequency, l.next_due_date, l.is_active)
            for l in linhas]


def _historico(account_id, user_id, nome_chave: str, dia: date) -> list[tuple[date, Decimal]]:
    """Gastos antigos com o mesmo favorecido/descrição (só os que o usuário pode ver)."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT payee, description, transaction_date, amount FROM transactions"
                " WHERE account_id = :conta AND voided_at IS NULL AND transaction_type = 'expense'"
                " AND (scope = 'conjunto' OR created_by_user_id = :usuario)"
                " AND transaction_date >= :desde"
            ),
            {"conta": account_id, "usuario": user_id, "desde": dia - timedelta(days=DIAS_DE_HISTORICO)},
        ).all()
    return [(l.transaction_date, l.amount) for l in linhas if chave(l.payee or l.description or "") == nome_chave]


def _guardar_vencimento(conta_id: str, vencimento: date) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text("UPDATE recurring_transactions SET next_due_date = :data WHERE id = :id"),
            {"data": vencimento, "id": conta_id},
        )


def _criar(account_id, user_id, dados: dict, ativa: bool) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recurring_transactions (account_id, created_by_user_id, category_id,"
                " payee, amount, frequency, next_due_date, scope, is_active)"
                " VALUES (:conta, :usuario, :categoria, :nome, :valor, 'monthly', :proximo,"
                " :escopo, :ativa)"
            ),
            {
                "conta": account_id,
                "usuario": user_id,
                "categoria": dados["categoria_id"],
                "nome": dados["nome"],
                "valor": Decimal(dados["valor"]),
                "proximo": proximo_mes(date.fromisoformat(dados["data"])),
                "escopo": dados["escopo"],
                "ativa": ativa,
            },
        )


# ---------- conversa ----------

def _pergunta(dados: dict, meses: int) -> Resposta:
    valor = formatar_reais(Decimal(dados["valor"]))
    return Resposta(
        f"{dados['nome']} (~{valor}) apareceu em {meses} meses.\n"
        "É uma conta recorrente? Se for, entra no /fixos e na previsão.",
        BOTOES,
    )


def verificar_recorrente(telefone: str, account_id, user_id, dados: dict, categoria) -> Resposta | None:
    """Depois de gravar um gasto: se parece recorrente, pergunta com botões [Sim] [Não].

    Se a conta já é conhecida, só atualiza o próximo vencimento.
    """
    if dados.get("aprender") is False:
        return None  # sem favorecido (comprovante ilegível) não dá para reconhecer
    nome = (dados.get("favorecido") or dados["descricao"]).strip()
    nome_chave = chave(nome)
    dia = date.fromisoformat(dados["data"]) if dados.get("data") else financas.hoje()
    conhecidas = [c for c in contas_da_conta(account_id, user_id) if chave(c.nome) == nome_chave]
    if conhecidas:
        for conta in conhecidas:
            if conta.ativa:
                vencimento = avancar_vencimento(conta.proximo, dia)
                if vencimento:
                    _guardar_vencimento(conta.id, vencimento)
        return None  # já respondida (sim ou não): não pergunta de novo
    valor = Decimal(dados["valor"])
    meses = meses_parecidos(valor, dia, _historico(account_id, user_id, nome_chave, dia))
    if meses < MESES_MINIMOS:
        return None
    novos = {"nome": nome, "valor": str(valor), "data": dia.isoformat(),
             "categoria_id": categoria.id, "escopo": dados["escopo"], "meses": meses}
    salvar_estado(telefone, ESTADO, novos)
    return _pergunta(novos, meses)


def continuar_recorrente(telefone: str, dados: dict, texto: str) -> str | Resposta:
    if not (eh_sim(texto) or eh_nao(texto)):
        resposta = _pergunta(dados, dados["meses"])
        resposta.texto = "Responda Sim ou Não.\n" + resposta.texto
        return resposta
    user_id, account_id = conta_do_usuario(telefone)
    limpar_estado(telefone)
    if eh_sim(texto):
        _criar(account_id, user_id, dados, True)
        vence = proximo_mes(date.fromisoformat(dados["data"]))
        return f"Anotado: {dados['nome']} é recorrente. Próximo vencimento: {vence:%d/%m/%Y}. Veja em /fixos."
    _criar(account_id, user_id, dados, False)
    return f"Certo, não pergunto mais sobre {dados['nome']}."
