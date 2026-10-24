"""Cálculos financeiros em Python (a IA nunca calcula)."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import text

from app.db import get_engine

BRASIL = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem horário de verão desde 2019)

SEM_CATEGORIA = "Sem categoria"


def hoje() -> date:
    return datetime.now(BRASIL).date()


# ---------- períodos ----------

# Um período e o anterior, para comparar: (início, fim, início anterior, fim anterior).
Periodos = tuple[date, date, date, date]


def periodos_do_mes(dia: date) -> Periodos:
    """Do dia 1 até hoje, e o mesmo trecho do mês passado (assim a comparação é justa)."""
    inicio = dia.replace(day=1)
    fim_anterior = inicio - timedelta(days=1)
    inicio_anterior = fim_anterior.replace(day=1)
    return inicio, dia, inicio_anterior, fim_anterior.replace(day=min(dia.day, fim_anterior.day))


def periodos_da_semana(dia: date) -> Periodos:
    """De segunda até hoje, e o mesmo trecho da semana passada."""
    inicio = dia - timedelta(days=dia.weekday())
    inicio_anterior = inicio - timedelta(days=7)
    return inicio, dia, inicio_anterior, inicio_anterior + (dia - inicio)


# ---------- totais ----------

class Totais:
    """Entradas e saídas de um período, já respeitando a privacidade do casal."""

    def __init__(self) -> None:
        self.entradas = Decimal("0")
        self.por_tipo: dict[str, Decimal] = {}  # saídas que o usuário pode ver em detalhe
        self.pessoais_do_parceiro = Decimal("0")  # saídas "meu" do parceiro: só o total

    @property
    def saidas(self) -> Decimal:
        return sum(self.por_tipo.values(), Decimal("0")) + self.pessoais_do_parceiro

    @property
    def saldo(self) -> Decimal:
        return self.entradas - self.saidas

    @property
    def vazio(self) -> bool:
        return self.entradas == 0 and self.saidas == 0


def somar(linhas) -> Totais:
    """Linhas (tipo da transação, tipo da categoria, é pessoal do parceiro?, total) -> Totais."""
    totais = Totais()
    for transacao, tipo, do_parceiro, total in linhas:
        if transacao == "income":
            totais.entradas += total  # a renda de cada um é visível ao parceiro
        elif do_parceiro:
            totais.pessoais_do_parceiro += total
        else:
            tipo = tipo or SEM_CATEGORIA
            totais.por_tipo[tipo] = totais.por_tipo.get(tipo, Decimal("0")) + total
    return totais


def totais_do_periodo(account_id, user_id, inicio: date, fim: date) -> Totais:
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT t.transaction_type, c.type,"
                " (t.scope = 'meu' AND t.created_by_user_id <> :usuario) AS do_parceiro,"
                " SUM(t.amount) FROM transactions t"
                " LEFT JOIN categories c ON c.id = t.category_id"
                " WHERE t.account_id = :conta AND t.voided_at IS NULL"
                " AND t.transaction_date BETWEEN :inicio AND :fim"
                " GROUP BY 1, 2, 3"
            ),
            {"conta": account_id, "usuario": user_id, "inicio": inicio, "fim": fim},
        ).all()
    return somar(linhas)


def variacao_pct(atual: Decimal, anterior: Decimal) -> int | None:
    """Variação em % (inteiro). None se não havia nada antes para comparar."""
    if anterior == 0:
        return None
    return int(((atual - anterior) / anterior * 100).quantize(Decimal("1")))


# ---------- renda do mês (esperada x recebida) ----------

@dataclass
class RendaMes:
    esperada: Decimal | None  # /renda do mês, ou o padrão do /inicio
    recebida: Decimal  # entradas registradas no mês

    def valor(self, mes_passado: bool) -> Decimal | None:
        """Mês atual ou futuro: a esperada, mas a recebida vale se for maior.
        Mês passado: a recebida, ou a esperada se nada foi recebido."""
        if mes_passado:
            return self.recebida if self.recebida > 0 else self.esperada
        if self.esperada is None:
            return self.recebida if self.recebida > 0 else None
        return max(self.esperada, self.recebida)


@dataclass
class RendaPessoa:
    user_id: str
    nome: str | None
    renda: RendaMes
    mes_passado: bool
    propria: bool  # True = a esperada veio do /renda do mês (False = padrão do /inicio)

    @property
    def valor(self) -> Decimal | None:
        return self.renda.valor(self.mes_passado)


def _decimal(valor) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))


def rendas_do_mes(account_id, dia: date) -> list[RendaPessoa]:
    """A renda de cada pessoa da conta no mês de `dia` (a mais antiga primeiro)."""
    inicio = dia.replace(day=1)
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT m.user_id, u.display_name, p.amount AS plano, m.expected_income AS padrao,"
                " (SELECT COALESCE(SUM(t.amount), 0) FROM transactions t"
                "  WHERE t.account_id = m.account_id AND t.created_by_user_id = m.user_id"
                "  AND t.transaction_type = 'income' AND t.voided_at IS NULL"
                "  AND t.transaction_date BETWEEN :inicio AND :fim) AS recebida"
                " FROM members m JOIN users u ON u.id = m.user_id"
                " LEFT JOIN income_plans p ON p.account_id = m.account_id"
                " AND p.user_id = m.user_id AND p.month = :inicio"
                " WHERE m.account_id = :conta ORDER BY m.joined_at"
            ),
            {"conta": account_id, "inicio": inicio, "fim": ultimo_dia_do_mes(dia)},
        ).all()
    passado = inicio < hoje().replace(day=1)
    return [
        RendaPessoa(
            str(l.user_id),
            l.display_name,
            RendaMes(_decimal(l.plano if l.plano is not None else l.padrao), _decimal(l.recebida) or Decimal("0")),
            passado,
            l.plano is not None,
        )
        for l in linhas
    ]


def renda_esperada_do_mes(account_id, dia: date) -> Decimal | None:
    """Só a renda esperada do mês (de todos da conta somada), sem olhar o que já foi recebido."""
    valores = [p.renda.esperada for p in rendas_do_mes(account_id, dia) if p.renda.esperada is not None]
    return sum(valores, Decimal("0")) if valores else None


def renda_do_mes(account_id, dia: date, user_id=None) -> Decimal | None:
    """Renda do mês de uma pessoa (user_id) ou de todos da conta somada. None se não há renda."""
    valores = [
        pessoa.valor
        for pessoa in rendas_do_mes(account_id, dia)
        if (user_id is None or pessoa.user_id == str(user_id)) and pessoa.valor is not None
    ]
    return sum(valores, Decimal("0")) if valores else None


# ---------- previsão do fim do mês ----------

def ultimo_dia_do_mes(dia: date) -> date:
    return (dia.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def tres_meses_anteriores(dia: date) -> tuple[date, date]:
    """Do dia 1 de três meses atrás até o último dia do mês passado."""
    fim = dia.replace(day=1) - timedelta(days=1)
    inicio = fim.replace(day=1)
    for _ in range(2):
        inicio = (inicio - timedelta(days=1)).replace(day=1)
    return inicio, fim


MIN_DIAS_HISTORICO = 14  # abaixo disso a estimativa ainda é pouco confiável


@dataclass
class Previsao:
    entradas: Decimal  # já entrou no mês
    saidas: Decimal  # já saiu no mês
    a_vencer: Decimal  # fixos, assinaturas e parcelas que ainda vencem
    media_diaria: Decimal  # média diária de gastos variáveis
    dias_restantes: int
    base_media: str  # "3 meses" ou "mes atual" (de onde veio a média)
    dias_historico: int | None = None  # dias desde o primeiro registro (None = não informado)
    renda_mes: Decimal | None = None  # renda do mês pela regra de renda_do_mes (None = sem renda cadastrada)

    @property
    def pouco_historico(self) -> bool:
        return self.dias_historico is not None and 0 < self.dias_historico < MIN_DIAS_HISTORICO

    @property
    def variaveis(self) -> Decimal:
        return (self.media_diaria * self.dias_restantes).quantize(Decimal("0.01"))

    @property
    def saidas_previstas(self) -> Decimal:
        """Quanto terá saído no fim do mês."""
        return self.saidas + self.a_vencer + self.variaveis

    @property
    def saldo_final(self) -> Decimal:
        """Saldo considerando só o que já foi recebido."""
        return self.entradas - self.saidas_previstas

    @property
    def saldo_com_renda_esperada(self) -> Decimal | None:
        """Saldo se a renda esperada do mês entrar toda (None = sem renda cadastrada)."""
        if self.renda_mes is None:
            return None
        return max(self.renda_mes, self.entradas) - self.saidas_previstas


def calcular_previsao(
    entradas: Decimal,
    saidas: Decimal,
    a_vencer: Decimal,
    media_diaria: Decimal,
    dias_restantes: int,
    base_media: str = "3 meses",
) -> Previsao:
    """Entradas - saídas - fixos que ainda vencem - (média diária de variáveis x dias restantes)."""
    return Previsao(entradas, saidas, a_vencer, media_diaria, max(dias_restantes, 0), base_media)


def _ocorrencias(proxima: date, frequencia: str, depois_de: date, ate: date) -> int:
    """Quantas vezes a conta vence entre o dia seguinte a depois_de e ate."""
    total = 0
    atual = proxima
    while atual <= ate:
        if atual > depois_de:
            total += 1
        if frequencia != "weekly":
            break  # mensal/anual: só a próxima data importa neste mês
        atual += timedelta(days=7)
    return total


def valor_a_vencer(contas, dia: date) -> Decimal:
    """Contas recorrentes (frequência, próximo vencimento, valor) que vencem depois de hoje, no mês."""
    fim = ultimo_dia_do_mes(dia)
    total = Decimal("0")
    for frequencia, proximo, valor in contas:
        if proximo is not None:
            total += valor * _ocorrencias(proximo, frequencia, dia, fim)
    return total


def a_vencer_no_mes(account_id, dia: date) -> Decimal:
    """Fixos recorrentes e parcelas que ainda vencem neste mês."""
    with get_engine().connect() as connection:
        contas = connection.execute(
            text(
                "SELECT frequency, next_due_date, amount FROM recurring_transactions"
                " WHERE account_id = :conta AND is_active AND next_due_date IS NOT NULL"
            ),
            {"conta": account_id},
        ).all()
        parcelas = connection.execute(
            text(
                "SELECT description, installment_amount, total_installments, first_due_date, due_day,"
                " paid_installments FROM installments WHERE account_id = :conta"
            ),
            {"conta": account_id},
        ).all()
    return valor_a_vencer(contas, dia) + valor_parcelas_a_vencer(
        [Parcelamento(p[0], p[1], p[2], p[3], p[4], pagas_registradas=p[5]) for p in parcelas], dia
    )


# ---------- parcelas e objetivos de poupança ----------

def somar_meses(dia: date, meses: int, dia_do_mes: int | None = None) -> date:
    """Anda `meses` meses (pode ser negativo); dia 31 vira o último dia do mês, se preciso."""
    ano, mes = divmod(dia.year * 12 + dia.month - 1 + meses, 12)
    primeiro = date(ano, mes + 1, 1)
    return primeiro.replace(day=min(dia_do_mes or dia.day, ultimo_dia_do_mes(primeiro).day))


def proximo_dia(dia_do_mes: int, hoje_: date) -> date:
    """Próxima vez que o dia do mês acontece depois de hoje."""
    neste_mes = somar_meses(hoje_, 0, dia_do_mes)
    return neste_mes if neste_mes > hoje_ else somar_meses(hoje_, 1, dia_do_mes)


@dataclass
class Parcelamento:
    nome: str
    valor: Decimal  # valor de cada parcela
    total: int
    primeiro_vencimento: date
    dia: int  # dia do mês em que vence
    id: str = ""  # linha no banco (vazio se ainda não foi gravada)
    pagas_registradas: int | None = None  # pagas de fato (/pagar); None = parcela antiga

    def vencimento(self, numero: int) -> date:
        """Data da parcela `numero` (a primeira é a 1)."""
        return somar_meses(self.primeiro_vencimento, numero - 1, self.dia)

    def pagas(self, dia: date) -> int:
        """Parcelas pagas: as registradas pelo /pagar; sem registro, as que já venceram até hoje."""
        if self.pagas_registradas is not None:
            return min(self.pagas_registradas, self.total)
        return sum(1 for n in range(1, self.total + 1) if self.vencimento(n) <= dia)

    def pendente_no_mes(self, dia: date) -> bool:
        """Falta pagar uma parcela que vence até o fim do mês (inclui atrasada)?"""
        proximo = self.proximo_vencimento(dia)
        return proximo is not None and proximo <= ultimo_dia_do_mes(dia)

    def restantes(self, dia: date) -> int:
        return self.total - self.pagas(dia)

    def falta_pagar(self, dia: date) -> Decimal:
        return self.valor * self.restantes(dia)

    def proximo_vencimento(self, dia: date) -> date | None:
        restantes = self.restantes(dia)
        return self.vencimento(self.total - restantes + 1) if restantes else None


def valor_parcelas_a_vencer(parcelamentos: list[Parcelamento], dia: date) -> Decimal:
    """Parcelas que ainda vencem depois de hoje, até o fim do mês."""
    fim = ultimo_dia_do_mes(dia)
    total = Decimal("0")
    for p in parcelamentos:
        proximo = p.proximo_vencimento(dia)
        if proximo is not None and proximo <= fim:
            total += p.valor
    return total


def meses_ate(prazo: date, dia: date) -> int:
    """Quantos meses (no mínimo 1) restam para guardar até o prazo."""
    meses = (prazo.year - dia.year) * 12 + prazo.month - dia.month
    return max(meses + (1 if prazo.day >= dia.day else 0), 1)


def guardar_por_mes(falta: Decimal, prazo: date, dia: date) -> Decimal:
    """Quanto guardar por mês para chegar no valor até o prazo (arredonda para cima)."""
    return (max(falta, Decimal("0")) / meses_ate(prazo, dia)).quantize(Decimal("0.01"), ROUND_CEILING)


def _gasto_variavel(account_id, inicio: date, fim: date, user_id=None) -> Decimal:
    """Soma dos gastos variáveis (e sem categoria) da conta, só o total (sem detalhe de ninguém).
    Com user_id, soma só o que esse usuário registrou."""
    filtro = " AND t.created_by_user_id = :usuario" if user_id is not None else ""
    with get_engine().connect() as connection:
        return connection.execute(
            text(
                "SELECT COALESCE(SUM(t.amount), 0) FROM transactions t"
                " LEFT JOIN categories c ON c.id = t.category_id"
                " WHERE t.account_id = :conta AND t.voided_at IS NULL"
                " AND t.transaction_type = 'expense'"
                " AND (c.type IS NULL OR c.type = 'Variável')"
                f" AND t.transaction_date BETWEEN :inicio AND :fim{filtro}"
            ),
            {"conta": account_id, "inicio": inicio, "fim": fim, "usuario": user_id},
        ).scalar_one()


def primeiro_registro(account_id, dia: date, user_id=None) -> date | None:
    """Data do registro mais antigo (até hoje). Dias antes dela não contam como "dias sem gasto"."""
    filtro = " AND created_by_user_id = :usuario" if user_id is not None else ""
    with get_engine().connect() as connection:
        return connection.execute(
            text(
                "SELECT MIN(transaction_date) FROM transactions"
                " WHERE account_id = :conta AND voided_at IS NULL"
                f" AND transaction_date <= :dia{filtro}"
            ),
            {"conta": account_id, "dia": dia, "usuario": user_id},
        ).scalar()


def dias_de_historico(primeiro: date | None, dia: date) -> int:
    """Quantos dias (contando hoje) desde o primeiro registro; 0 se ainda não há nenhum."""
    return 0 if primeiro is None else (dia - primeiro).days + 1


def media_diaria_variaveis(
    account_id, dia: date, user_id=None, primeiro: date | None = None
) -> tuple[Decimal, str]:
    """Média por dia dos variáveis nos 3 meses passados; sem histórico, usa o mês atual.

    Só conta os dias a partir do primeiro registro (`primeiro`; se None, busca no banco).
    """
    if primeiro is None:
        primeiro = primeiro_registro(account_id, dia, user_id)
    if primeiro is None:
        return Decimal("0"), "mes atual"
    inicio, fim = tres_meses_anteriores(dia)
    inicio = max(inicio, primeiro)
    if inicio <= fim:
        total = _gasto_variavel(account_id, inicio, fim, user_id)
        if total > 0:
            return total / ((fim - inicio).days + 1), "3 meses"
    inicio = max(dia.replace(day=1), primeiro)
    atual = _gasto_variavel(account_id, inicio, dia, user_id)
    return atual / ((dia - inicio).days + 1), "mes atual"


def previsao_do_mes(account_id, user_id, dia: date) -> Previsao:
    totais = totais_do_periodo(account_id, user_id, dia.replace(day=1), dia)
    primeiro = primeiro_registro(account_id, dia)
    media, base = media_diaria_variaveis(account_id, dia, primeiro=primeiro)
    previsao = calcular_previsao(
        totais.entradas,
        totais.saidas,
        a_vencer_no_mes(account_id, dia),
        media,
        (ultimo_dia_do_mes(dia) - dia).days,
        base,
    )
    previsao.dias_historico = dias_de_historico(primeiro, dia)
    previsao.renda_mes = renda_do_mes(account_id, dia)
    return previsao


# ---------- diagnóstico: real x meta por tipo ----------

# Estes tipos são alvos a atingir (guardar); os demais são tetos de gasto.
TIPOS_MINIMOS = ("Investimento", "Reserva de emergência")
TIPO_PROJETADO = "Variável"  # único tipo com projeção até o fim do mês (média diária)


@dataclass
class ItemDiagnostico:
    tipo: str
    meta: Decimal
    real: Decimal
    projetado: Decimal  # quanto o tipo deve somar no fim do mês
    minimo: bool  # True: a meta é um mínimo a guardar

    @property
    def situacao(self) -> str:
        """"ok", "estourou" (já passou do teto), "vai_estourar" ou "falta" (abaixo do mínimo)."""
        if self.minimo:
            return "ok" if self.real >= self.meta else "falta"
        if self.real > self.meta:
            return "estourou"
        return "vai_estourar" if self.projetado > self.meta else "ok"

    @property
    def sinal(self) -> str:
        """✅ dentro, ⚠️ perto do limite (90% ou mais), ❌ fora. Em mínimos, o problema é ficar abaixo."""
        if self.situacao in ("estourou", "vai_estourar"):
            return "❌"
        if self.minimo:
            if self.situacao == "ok":
                return "✅"
            return "⚠️" if self.real >= self.meta * Decimal("0.9") else "❌"
        return "⚠️" if self.projetado >= self.meta * Decimal("0.9") else "✅"

    @property
    def excesso(self) -> Decimal:
        """Quanto já passou do teto (só quando estourou)."""
        return self.real - self.meta if self.situacao == "estourou" else Decimal("0")

    @property
    def ajuste(self) -> Decimal:
        """Quanto cortar (vai_estourar) ou guardar (falta) até o fim do mês."""
        if self.situacao == "vai_estourar":
            return self.projetado - self.meta
        if self.situacao == "falta":
            return self.meta - self.real
        return Decimal("0")


def semanas_restantes(dias_restantes: int) -> Decimal:
    """Semanas que faltam para o fim do mês (no mínimo 1, para não dividir por zero)."""
    return max(Decimal(dias_restantes) / 7, Decimal("1"))


def ajuste_por_semana(item: ItemDiagnostico, dias_restantes: int) -> Decimal:
    return (item.ajuste / semanas_restantes(dias_restantes)).quantize(Decimal("0.01"))


def diagnosticar(
    metas: dict[str, Decimal], real_por_tipo: dict[str, Decimal], variaveis_restantes: Decimal
) -> list[ItemDiagnostico]:
    """Compara o real de cada tipo com a meta (em R$). Só entram os tipos que têm meta."""
    itens = []
    for tipo, meta in metas.items():
        real = real_por_tipo.get(tipo, Decimal("0"))
        projetado = real + variaveis_restantes if tipo == TIPO_PROJETADO else real
        itens.append(ItemDiagnostico(tipo, meta, real, projetado, tipo in TIPOS_MINIMOS))
    return itens


def gastos_do_usuario_por_tipo(account_id, user_id, inicio: date, fim: date) -> dict[str, Decimal]:
    """Saídas que o próprio usuário registrou (as "meu" dele incluídas), por tipo de categoria.
    Serve às metas individuais; o que o parceiro registrou nunca entra aqui."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT c.type, SUM(t.amount) FROM transactions t"
                " LEFT JOIN categories c ON c.id = t.category_id"
                " WHERE t.account_id = :conta AND t.created_by_user_id = :usuario"
                " AND t.voided_at IS NULL AND t.transaction_type = 'expense'"
                " AND t.transaction_date BETWEEN :inicio AND :fim GROUP BY 1"
            ),
            {"conta": account_id, "usuario": user_id, "inicio": inicio, "fim": fim},
        ).all()
    por_tipo: dict[str, Decimal] = {}
    for tipo, total in linhas:
        por_tipo[tipo or SEM_CATEGORIA] = total
    return por_tipo


def variaveis_restantes_do_usuario(account_id, user_id, dia: date) -> Decimal:
    """Quanto o usuário ainda deve gastar em variáveis até o fim do mês (média dele x dias que faltam)."""
    media, _ = media_diaria_variaveis(account_id, dia, user_id)
    return (media * (ultimo_dia_do_mes(dia) - dia).days).quantize(Decimal("0.01"))


def gasto_acumulado_por_dia(account_id, dia: date) -> list[Decimal]:
    """Saídas acumuladas do dia 1 até hoje (uma posição por dia)."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT transaction_date, SUM(amount) FROM transactions"
                " WHERE account_id = :conta AND voided_at IS NULL"
                " AND transaction_type = 'expense'"
                " AND transaction_date BETWEEN :inicio AND :fim GROUP BY 1"
            ),
            {"conta": account_id, "inicio": dia.replace(day=1), "fim": dia},
        ).all()
    return acumular({data.day: total for data, total in linhas}, dia.day)


def acumular(por_dia: dict[int, Decimal], ate_dia: int) -> list[Decimal]:
    acumulado, soma = [], Decimal("0")
    for numero in range(1, ate_dia + 1):
        soma += por_dia.get(numero, Decimal("0"))
        acumulado.append(soma)
    return acumulado
