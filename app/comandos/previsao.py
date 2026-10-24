from decimal import Decimal

from app import financas, graficos
from app.comandos.cadastro import conta_do_usuario
from app.comandos.formato import formatar_reais, normalizar
from app.comandos.metas import em_reais, ler_metas, ler_renda_conjunta
from app.comandos.resposta import Resposta

AJUDA_GRAFICO = "Use /grafico previsao"
MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


def _reais(valor: Decimal) -> str:
    return f"-{formatar_reais(-valor)}" if valor < 0 else formatar_reais(valor)


def montar_previsao(previsao: financas.Previsao, fim_do_mes) -> str:
    p = previsao
    linhas = [
        f"Previsão até {fim_do_mes:%d/%m} ({p.dias_restantes} dias restantes):",
        f"Já entrou {_reais(p.entradas)} e saiu {_reais(p.saidas)}.",
        f"Ainda vence {_reais(p.a_vencer)} e os variáveis devem somar {_reais(p.variaveis)}.",
    ]
    esperado = p.saldo_com_renda_esperada
    if esperado is not None and p.renda_mes > p.entradas:
        linhas += [
            f"Renda do mês: recebido {_reais(p.entradas)} x esperado {_reais(p.renda_mes)}.",
            f"Saldo previsto no fim do mês, com a renda esperada: {_reais(esperado)}",
            f"Saldo só com o que já recebeu: {_reais(p.saldo_final)}",
        ]
    else:
        linhas.append(f"Saldo previsto no fim do mês: {_reais(p.saldo_final)}")
    if p.pouco_historico:
        linhas.append(
            f"Atenção: só tenho {p.dias_historico} dia(s) de histórico. "
            "A estimativa ainda é pouco confiável."
        )
    saldo = p.saldo_final if esperado is None else esperado
    if p.renda_mes is None and p.entradas == 0:
        linhas.append("Sem entradas registradas: use /entrada VALOR para a previsão ficar certa.")
    elif saldo < 0:
        linhas.append("Vai fechar no vermelho. Corte os variáveis já.")
    return "\n".join(linhas)


def _sem_registros(previsao: financas.Previsao) -> bool:
    return previsao.entradas == 0 and previsao.saidas == 0 and previsao.a_vencer == 0


def comando_previsao(telefone: str, argumentos: str) -> str:
    dia = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    previsao = financas.previsao_do_mes(account_id, user_id, dia)
    if _sem_registros(previsao):
        return "Ainda não há registros neste mês. Use /gasto ou /entrada para começar."
    return montar_previsao(previsao, financas.ultimo_dia_do_mes(dia))


def limite_das_metas(account_id, user_id) -> Decimal | None:
    """Soma das metas do mês em R$ (None se não há meta que dê para converter)."""
    renda = ler_renda_conjunta(account_id)  # no casal, as duas rendas
    valores = [em_reais(formato, valor, renda) for formato, valor in ler_metas(account_id).values()]
    valores = [v for v in valores if v is not None]
    return sum(valores, Decimal("0")) if valores else None


def comando_grafico(telefone: str, argumentos: str) -> str | Resposta:
    if normalizar(argumentos).strip() != "previsao":
        return AJUDA_GRAFICO
    dia = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    previsao = financas.previsao_do_mes(account_id, user_id, dia)
    if _sem_registros(previsao):
        return "Ainda não há registros neste mês. Use /gasto ou /entrada para começar."
    limite = limite_das_metas(account_id, user_id)
    imagem = graficos.grafico_previsao(
        financas.gasto_acumulado_por_dia(account_id, dia),
        financas.ultimo_dia_do_mes(dia).day,
        previsao.saidas_previstas,
        limite,
        f"Gastos de {MESES[dia.month - 1]}/{dia.year}",
    )
    legenda = f"Projeção: saem {_reais(previsao.saidas_previstas)} até o fim do mês."
    if limite:
        legenda += f" Suas metas somam {_reais(limite)}."
    else:
        legenda += " Defina metas em /metas para ver a linha 'deveria estar'."
    return Resposta(texto=legenda, imagem=imagem)
