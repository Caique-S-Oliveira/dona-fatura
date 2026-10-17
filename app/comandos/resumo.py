from datetime import date
from decimal import Decimal

from app import financas
from app.comandos.cadastro import conta_do_usuario
from app.comandos.formato import formatar_reais, normalizar
from app.financas import Totais

MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)
AJUDA = "Use /resumo para o mês ou /resumo semana para a semana."


def _reais(valor: Decimal) -> str:
    return f"-{formatar_reais(-valor)}" if valor < 0 else formatar_reais(valor)


def _variacao(atual: Decimal, anterior: Decimal) -> str:
    pct = financas.variacao_pct(atual, anterior)
    if pct is None:
        return ""
    return f" ({pct:+d}%)" if pct else " (igual)"


def _periodo(inicio: date, fim: date) -> str:
    if inicio == fim:
        return fim.strftime("%d/%m")
    return f"{inicio:%d} a {fim:%d/%m}"


def montar_resumo(titulo: str, periodos: financas.Periodos, atual: Totais, anterior: Totais) -> str:
    inicio, fim, inicio_ant, fim_ant = periodos
    linhas = [
        f"{titulo} ({_periodo(inicio, fim)}):",
        f"Entradas: {_reais(atual.entradas)}{_variacao(atual.entradas, anterior.entradas)}",
        f"Saídas: {_reais(atual.saidas)}{_variacao(atual.saidas, anterior.saidas)}",
    ]
    for tipo, total in sorted(atual.por_tipo.items(), key=lambda item: -item[1]):
        linhas.append(f"  • {tipo}: {_reais(total)}")
    if atual.pessoais_do_parceiro:
        linhas.append(f"  • Gastos pessoais do parceiro: {_reais(atual.pessoais_do_parceiro)}")
    linhas.append(f"Saldo: {_reais(atual.saldo)}")
    if atual.saldo < 0:
        linhas.append("Você gastou mais do que entrou. Hora de segurar.")
    if anterior.vazio:
        linhas.append(f"(Sem registros em {_periodo(inicio_ant, fim_ant)} para comparar.)")
    else:
        linhas.append(f"(Variação x {_periodo(inicio_ant, fim_ant)}/{fim_ant:%Y}.)")
    return "\n".join(linhas)


def comando_resumo(telefone: str, argumentos: str) -> str:
    pedido = normalizar(argumentos).strip()
    dia = financas.hoje()
    if pedido in ("", "mes"):
        periodos = financas.periodos_do_mes(dia)
        titulo = f"Resumo de {MESES[dia.month - 1]}/{dia.year}"
    elif pedido == "semana":
        periodos = financas.periodos_da_semana(dia)
        titulo = "Resumo da semana"
    else:
        return AJUDA
    user_id, account_id = conta_do_usuario(telefone)
    inicio, fim, inicio_ant, fim_ant = periodos
    atual = financas.totais_do_periodo(account_id, user_id, inicio, fim)
    anterior = financas.totais_do_periodo(account_id, user_id, inicio_ant, fim_ant)
    if atual.vazio:
        return "Ainda não há registros neste período. Use /gasto ou /entrada para começar."
    return montar_resumo(titulo, periodos, atual, anterior)
