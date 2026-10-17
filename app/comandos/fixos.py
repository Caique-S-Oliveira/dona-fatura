"""/fixos: contas recorrentes do mês, quais já foram pagas e quais ainda vencem."""
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app import financas
from app.comandos.cadastro import conta_do_usuario
from app.comandos.categorias import chave
from app.comandos.formato import formatar_reais
from app.comandos.previsao import MESES
from app.comandos.recorrentes import ContaRecorrente
from app.db import get_engine

SEM_CONTAS = (
    "Você ainda não tem contas recorrentes.\n"
    "Quando uma conta se repetir em 2 meses, eu pergunto se ela é fixa."
)

Gasto = tuple[str, date, Decimal]  # (chave do favorecido, data, valor)


def _contas(account_id, user_id) -> list[ContaRecorrente]:
    """Contas ativas que o usuário pode ver (as "meu" do parceiro ficam de fora)."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT id, payee, amount, frequency, next_due_date FROM recurring_transactions"
                " WHERE account_id = :conta AND is_active"
                " AND (scope = 'conjunto' OR created_by_user_id = :usuario)"
            ),
            {"conta": account_id, "usuario": user_id},
        ).all()
    return [ContaRecorrente(str(l.id), l.payee, l.amount, l.frequency, l.next_due_date, True)
            for l in linhas]


def _gastos_do_mes(account_id, user_id, dia: date) -> list[Gasto]:
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT payee, description, transaction_date, amount FROM transactions"
                " WHERE account_id = :conta AND voided_at IS NULL AND transaction_type = 'expense'"
                " AND (scope = 'conjunto' OR created_by_user_id = :usuario)"
                " AND transaction_date BETWEEN :inicio AND :fim"
            ),
            {"conta": account_id, "usuario": user_id,
             "inicio": dia.replace(day=1), "fim": financas.ultimo_dia_do_mes(dia)},
        ).all()
    return [(chave(l.payee or l.description or ""), l.transaction_date, l.amount) for l in linhas]


def _vence_neste_mes(conta: ContaRecorrente, dia: date) -> bool:
    return conta.frequencia != "yearly" or (conta.proximo is not None and conta.proximo.month == dia.month)


def _dia_de_vencimento(conta: ContaRecorrente, dia: date) -> int | None:
    if conta.proximo is None:
        return None
    return min(conta.proximo.day, financas.ultimo_dia_do_mes(dia).day)


def montar_fixos(contas: list[ContaRecorrente], gastos: list[Gasto], dia: date) -> str:
    """Pagas (há gasto do mesmo favorecido no mês), a vencer e atrasadas, com os totais."""
    itens = []  # (dia do vencimento, linha)
    pago = faltam = Decimal("0")
    for conta in (c for c in contas if _vence_neste_mes(c, dia)):
        vencimento = _dia_de_vencimento(conta, dia)
        pagamentos = sorted((d, v) for k, d, v in gastos if k == chave(conta.nome))
        if pagamentos:
            quando, valor = pagamentos[-1]
            pago += valor
            linha = f"✅ {conta.nome} {formatar_reais(valor)} — pago em {quando:%d/%m}"
        else:
            faltam += conta.valor
            if vencimento is None:
                situacao = "ainda não pago"
            elif vencimento > dia.day:
                situacao = f"vence dia {vencimento}"
            elif vencimento == dia.day:
                situacao = "vence hoje"
            else:
                situacao = f"venceu dia {vencimento}, não achei o pagamento"
            icone = "⚠️" if vencimento is not None and vencimento < dia.day else "⏳"
            linha = f"{icone} {conta.nome} {formatar_reais(conta.valor)} — {situacao}"
        itens.append((vencimento or 0, linha))
    if not itens:
        return SEM_CONTAS
    itens.sort(key=lambda item: item[0])
    cabecalho = f"Fixos de {MESES[dia.month - 1]} ({len(itens)} contas):"
    rodape = f"Pago {formatar_reais(pago)}. Ainda falta {formatar_reais(faltam)}."
    return "\n".join([cabecalho, *(linha for _, linha in itens), rodape])


def comando_fixos(telefone: str, argumentos: str) -> str:
    dia = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    return montar_fixos(_contas(account_id, user_id), _gastos_do_mes(account_id, user_id, dia), dia)
