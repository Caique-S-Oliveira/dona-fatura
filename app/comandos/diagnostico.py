import re
from datetime import date
from decimal import Decimal

from app import financas, ia
from app.comandos.cadastro import conta_do_usuario
from app.comandos.casal import conta_em_casal
from app.comandos.metas import TIPOS, em_reais, ler_metas, ler_renda, ler_renda_conjunta
from app.comandos.previsao import MESES, _reais
from app.financas import ItemDiagnostico

SEM_METAS = "Você ainda não tem metas. Mande /inicio ou /metas para definir."
SEM_REGISTROS = "Ainda não há registros neste mês. Use /gasto ou /entrada para começar."


def _ajuste(item: ItemDiagnostico, dias: int, fim: date) -> str:
    por_semana = _reais(financas.ajuste_por_semana(item, dias))
    if item.situacao == "estourou":
        return f"{item.tipo}: já passou {_reais(item.excesso)}; segure o resto do mês."
    if item.situacao == "vai_estourar":
        return f"{item.tipo}: fecha em {_reais(item.projetado)}; corte {por_semana} por semana até {fim:%d/%m}."
    return f"{item.tipo}: guarde {por_semana} por semana até {fim:%d/%m}."


def montar_diagnostico(
    itens: list[ItemDiagnostico],
    dia: date,
    saldo_previsto: Decimal | None,
    pessoais_do_parceiro: Decimal = Decimal("0"),
    titulo: str = "Diagnóstico",
) -> str:
    """Texto com os números prontos (serve de base para a IA e de plano B se ela falhar).

    saldo_previsto None = sem a linha do saldo (o saldo é da conta, não de uma meta individual).
    """
    fim = financas.ultimo_dia_do_mes(dia)
    dias = (fim - dia).days
    por_tipo = {item.tipo: item for item in itens}
    linhas = [f"{titulo} de {MESES[dia.month - 1]}/{dia.year} (faltam {dias} dias):"]
    for tipo in TIPOS:
        if tipo in por_tipo:
            item = por_tipo[tipo]
            linhas.append(f"{item.sinal} {tipo}: {_reais(item.real)} de {_reais(item.meta)}")
    if any(item.minimo for item in itens):
        linhas.append("Em Investimento e Reserva, o problema é ficar abaixo da meta.")
    fora = [por_tipo[tipo] for tipo in TIPOS if tipo in por_tipo and por_tipo[tipo].sinal == "❌"]
    if fora:
        linhas.append("Ajustes:")
        linhas += [_ajuste(item, dias, fim) for item in fora]
    sem_meta = [tipo for tipo in TIPOS if tipo not in por_tipo]
    if sem_meta:
        linhas.append(f"Sem meta: {', '.join(sem_meta)}. Defina em /metas.")
    if pessoais_do_parceiro:
        linhas.append(f"(Não inclui {_reais(pessoais_do_parceiro)} de gastos pessoais do parceiro.)")
    if saldo_previsto is not None:
        linhas.append(f"Saldo previsto no fim do mês: {_reais(saldo_previsto)}")
    return "\n".join(linhas)


def _numeros(texto: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)*", texto))


def texto_final(fatos: str) -> str:
    """A IA reescreve no tom da Dona Fatura; se falhar ou trouxer número novo, vale o texto pronto."""
    escrito = ia.escrever_diagnostico(fatos)
    if escrito is None or not _numeros(escrito) <= _numeros(fatos):
        return fatos
    return escrito


def _metas_em_reais(metas, renda) -> dict[str, Decimal]:
    em_reais_ = {tipo: em_reais(formato, valor, renda) for tipo, (formato, valor) in metas.items()}
    return {tipo: reais for tipo, reais in em_reais_.items() if reais is not None}


def _diagnostico_individual(account_id, user_id, dia: date) -> str | None:
    """Metas só suas (no casal) contra o que você mesmo registrou. None se não tem metas."""
    metas = _metas_em_reais(ler_metas(account_id, user_id), ler_renda(account_id, user_id))
    if not metas:
        return None
    real = financas.gastos_do_usuario_por_tipo(account_id, user_id, dia.replace(day=1), dia)
    restantes = financas.variaveis_restantes_do_usuario(account_id, user_id, dia)
    itens = financas.diagnosticar(metas, real, restantes)
    return montar_diagnostico(itens, dia, None, titulo="Diagnóstico só seu")


def comando_diagnostico(telefone: str, argumentos: str) -> str:
    dia = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    # No casal as metas do casal usam as duas rendas; sozinho, é a renda do próprio usuário.
    metas = _metas_em_reais(ler_metas(account_id), ler_renda_conjunta(account_id))
    individual = _diagnostico_individual(account_id, user_id, dia) if conta_em_casal(account_id) else None
    if not metas and individual is None:
        return SEM_METAS
    totais = financas.totais_do_periodo(account_id, user_id, dia.replace(day=1), dia)
    previsao = financas.previsao_do_mes(account_id, user_id, dia)
    if totais.vazio and previsao.a_vencer == 0:
        return SEM_REGISTROS
    blocos = []
    if metas:
        itens = financas.diagnosticar(metas, totais.por_tipo, previsao.variaveis)
        blocos.append(montar_diagnostico(itens, dia, previsao.saldo_final, totais.pessoais_do_parceiro))
    if individual is not None:
        blocos.append(individual)
    return texto_final("\n\n".join(blocos))
