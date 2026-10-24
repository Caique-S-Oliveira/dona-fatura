"""/renda: renda esperada por mês (para quem tem renda que varia, como autônomos).

A renda do /inicio é o padrão; /renda MÊS VALOR define um valor só para aquele mês.
A regra de qual valor vale em cada mês está em financas.RendaMes.
"""
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app import financas
from app.comandos.cadastro import conta_do_usuario
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import (
    MESES,
    eh_nao,
    eh_sim,
    formatar_reais,
    ler_numero,
    mes_e_ano,
    normalizar,
)
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "renda"
BOTOES = ("Sim", "Corrigir")
BOTOES_DUPLICADA = ("Registrar", "Só a renda")
MAX_MESES = 12
VALOR_MAXIMO = Decimal("99999999.99")
DESCRICAO = "Renda"
AJUDA = (
    "Use: /renda outubro 5000\n"
    "Vários meses: /renda outubro 5000, novembro 3000\n"
    "Já recebida: /renda outubro 5000 recebido (ou recebido dia 5)\n"
    "Tirar o valor de um mês: /renda outubro 0\n"
    "Para ver os meses: /renda"
)

_MES_E_ANO = re.compile(r"^([a-z0-9]+)/(\d{4})$")
_RECEBIDO = re.compile(r"\brecebid[oa]\b(?:\s+(?:no\s+)?dia\s+(\d{1,2}))?")
# Vírgula entre meses: seguida de letra ("..., novembro") ou de espaço e mês numérico ("..., 11 4000").
# A vírgula do valor ("4.500,00") não separa nada.
_SEPARADOR = re.compile(r",\s*(?=[^\W\d_])|,\s+(?=\d{1,2}[\s/])|;")


@dataclass
class Item:
    mes: date  # sempre o dia 1
    valor: Decimal  # 0 = tirar o valor do mês
    recebido: bool = False
    dia: int | None = None

    @property
    def data_recebimento(self) -> date:
        return self.mes.replace(day=self.dia or 1)

    def para_estado(self) -> dict:
        return {"mes": self.mes.isoformat(), "valor": str(self.valor), "recebido": self.recebido, "dia": self.dia}

    @classmethod
    def do_estado(cls, dados: dict) -> "Item":
        return cls(date.fromisoformat(dados["mes"]), Decimal(dados["valor"]), dados["recebido"], dados["dia"])


# ---------- leitura do pedido ----------

def _numero_do_mes(token: str) -> int | None:
    """"outubro", "out", "10" -> 10. Abreviação precisa ter 3 letras e servir para um mês só."""
    if token.isdigit():
        return int(token) if 1 <= int(token) <= 12 else None
    if len(token) < 3:
        return None
    achados = [n for n, nome in enumerate(MESES, 1) if normalizar(nome).startswith(token)]
    return achados[0] if len(achados) == 1 else None


def _ler_mes(token: str, hoje: date, recebido: bool) -> date | None:
    """Mês com ano (10/2026, outubro/2026) ou sem ano.

    Sem ano: o mês que vem a seguir (este ano, ou o próximo se já passou). Com "recebido", o mês
    mais recente (este ano, ou o ano passado se ainda não chegou), porque receber é no passado.
    """
    com_ano = _MES_E_ANO.match(token)
    numero = _numero_do_mes(com_ano[1] if com_ano else token)
    if numero is None:
        return None
    if com_ano:
        ano = int(com_ano[2])
        return date(ano, numero, 1) if 2000 <= ano <= 2100 else None
    ano = hoje.year
    if recebido and numero > hoje.month:
        ano -= 1
    elif not recebido and numero < hoje.month:
        ano += 1
    return date(ano, numero, 1)


def _ler_item(trecho: str, hoje: date) -> Item:
    """"outubro 5000 recebido dia 5" -> Item. ValueError com a mensagem para o usuário."""
    texto = normalizar(trecho)
    recebido, dia = False, None
    achado = _RECEBIDO.search(texto)
    if achado:
        recebido = True
        dia = int(achado[1]) if achado[1] else None
        texto = texto[: achado.start()] + " " + texto[achado.end():]
    palavras = [p for p in texto.split() if p != "r$"]
    if len(palavras) != 2:
        raise ValueError(f"Não entendi \"{trecho.strip()}\".\n{AJUDA}")
    mes = _ler_mes(palavras[0], hoje, recebido)
    valor = ler_numero(palavras[1])
    if mes is None or valor is None:
        raise ValueError(f"Não entendi \"{trecho.strip()}\".\n{AJUDA}")
    if valor > VALOR_MAXIMO:
        raise ValueError("Esse valor é grande demais. Confira e mande de novo.")
    if valor == 0 and recebido:
        raise ValueError(f"Para tirar o valor de {mes_e_ano(mes)}, mande só: /renda {palavras[0]} 0")
    if dia is not None and not 1 <= dia <= financas.ultimo_dia_do_mes(mes).day:
        raise ValueError(f"{mes_e_ano(mes)} não tem dia {dia}.")
    return Item(mes, valor, recebido, dia)


def ler_pedido(argumentos: str, hoje: date) -> list[Item]:
    """"outubro 5000, nov 4000 recebido" -> itens. ValueError com a mensagem para o usuário."""
    trechos = [t for t in _SEPARADOR.split(argumentos) if t.strip()]
    if not trechos:
        raise ValueError(AJUDA)
    if len(trechos) > MAX_MESES:
        raise ValueError(f"Mande no máximo {MAX_MESES} meses por vez.")
    itens: dict[date, Item] = {}
    for trecho in trechos:
        item = _ler_item(trecho, hoje)
        if item.mes in itens:
            raise ValueError(f"{mes_e_ano(item.mes)} apareceu duas vezes. Mande um valor só por mês.")
        itens[item.mes] = item
    return list(itens.values())


# ---------- banco de dados ----------

def _padrao(account_id, user_id) -> Decimal | None:
    with get_engine().connect() as connection:
        valor = connection.execute(
            text("SELECT expected_income FROM members WHERE account_id = :conta AND user_id = :usuario"),
            {"conta": account_id, "usuario": user_id},
        ).scalar()
    return None if valor is None else Decimal(str(valor))


def _entrada_igual_no_mes(connection, account_id, user_id, item: Item) -> bool:
    return connection.execute(
        text(
            "SELECT 1 FROM transactions WHERE account_id = :conta AND created_by_user_id = :usuario"
            " AND transaction_type = 'income' AND voided_at IS NULL AND amount = :valor"
            " AND transaction_date BETWEEN :inicio AND :fim LIMIT 1"
        ),
        {"conta": account_id, "usuario": user_id, "valor": item.valor, "inicio": item.mes,
         "fim": financas.ultimo_dia_do_mes(item.mes)},
    ).first() is not None


def _repetidas(account_id, user_id, itens: list[Item]) -> list[Item]:
    """Itens "recebido" cujo valor já foi registrado como entrada no mesmo mês."""
    with get_engine().connect() as connection:
        return [i for i in itens if i.recebido and _entrada_igual_no_mes(connection, account_id, user_id, i)]


def _salvar(account_id, user_id, itens: list[Item], nao_registrar: set[date]) -> None:
    """Grava as rendas dos meses e as entradas recebidas, tudo numa transação só."""
    with get_engine().begin() as connection:
        for item in itens:
            parametros = {"conta": account_id, "usuario": user_id, "mes": item.mes, "valor": item.valor}
            if item.valor == 0:
                connection.execute(
                    text("DELETE FROM income_plans WHERE account_id = :conta AND user_id = :usuario"
                         " AND month = :mes"),
                    parametros,
                )
                continue
            connection.execute(
                text(
                    "INSERT INTO income_plans (account_id, user_id, month, amount)"
                    " VALUES (:conta, :usuario, :mes, :valor)"
                    " ON CONFLICT (account_id, user_id, month)"
                    " DO UPDATE SET amount = EXCLUDED.amount, updated_at = CURRENT_TIMESTAMP"
                ),
                parametros,
            )
            if item.recebido and item.mes not in nao_registrar:
                connection.execute(
                    text(
                        "INSERT INTO transactions (account_id, created_by_user_id, transaction_type,"
                        " amount, description, transaction_date, scope, source)"
                        " VALUES (:conta, :usuario, 'income', :valor, :descricao, :data, 'conjunto', 'manual')"
                    ),
                    {**parametros, "descricao": DESCRICAO, "data": item.data_recebimento},
                )


# ---------- textos ----------

def _reais_ou_nada(valor: Decimal | None) -> str:
    return formatar_reais(valor) if valor is not None else "sem renda"


def _linha_item(item: Item, padrao: Decimal | None) -> str:
    mes = mes_e_ano(item.mes)
    if item.valor == 0:
        return f"• {mes}: tirar o valor do mês (volta ao padrão: {_reais_ou_nada(padrao)})"
    linha = f"• {mes}: {formatar_reais(item.valor)}"
    if item.recebido:
        data = item.data_recebimento
        linha += f", já recebido em {data:%d/%m/%Y}"
        if data > financas.hoje():
            linha += " (essa data ainda não chegou)"
    return linha


def _pergunta(dados: dict) -> Resposta:
    padrao = Decimal(dados["padrao"]) if dados.get("padrao") else None
    itens = [Item.do_estado(i) for i in dados["itens"]]
    linhas = [_linha_item(i, padrao) for i in itens]
    return Resposta("Salvar a renda esperada?\n" + "\n".join(linhas), BOTOES)


def _listar(account_id, user_id) -> str:
    dia = financas.hoje()
    with get_engine().connect() as connection:
        pessoas = connection.execute(
            text("SELECT m.user_id, u.display_name, m.expected_income FROM members m"
                 " JOIN users u ON u.id = m.user_id WHERE m.account_id = :conta ORDER BY m.joined_at"),
            {"conta": account_id},
        ).all()
        planos = connection.execute(
            text("SELECT user_id, month, amount FROM income_plans WHERE account_id = :conta ORDER BY month"),
            {"conta": account_id},
        ).all()
    if not any(p.expected_income is not None for p in pessoas) and not planos:
        return "Você ainda não tem renda cadastrada. Mande /inicio, ou /renda outubro 5000.\n" + AJUDA
    blocos = []
    for pessoa in pessoas:
        meus = [p for p in planos if str(p.user_id) == str(pessoa.user_id)][-MAX_MESES:]
        quem = "Sua" if str(pessoa.user_id) == str(user_id) else f"A de {pessoa.display_name or 'seu parceiro(a)'}"
        padrao = Decimal(str(pessoa.expected_income)) if pessoa.expected_income is not None else None
        linhas = [f"{quem} renda esperada (padrão: {_reais_ou_nada(padrao)}):"]
        linhas += [f"• {mes_e_ano(p.month)}: {formatar_reais(Decimal(str(p.amount)))}" for p in meus]
        if not meus:
            linhas.append("Nenhum mês com valor próprio.")
        blocos.append("\n".join(linhas))
    texto = "\n".join(blocos)
    total = financas.renda_do_mes(account_id, dia)
    if len(pessoas) > 1 and total is not None:
        texto += f"\nRenda do casal em {mes_e_ano(dia)}: {formatar_reais(total)} (soma das duas)."
    return texto + "\nMeses sem valor próprio usam o padrão. Para mudar: /renda outubro 5000"


# ---------- conversa ----------

def _pedir(telefone: str, argumentos: str, user_id, account_id) -> str | Resposta:
    try:
        itens = ler_pedido(argumentos, financas.hoje())
    except ValueError as erro:
        return str(erro)
    padrao = _padrao(account_id, user_id)
    dados = {"passo": "confirmar", "itens": [i.para_estado() for i in itens],
             "padrao": str(padrao) if padrao is not None else None}
    salvar_estado(telefone, ESTADO, dados)
    return _pergunta(dados)


def comando_renda(telefone: str, argumentos: str) -> str | Resposta:
    user_id, account_id = conta_do_usuario(telefone)
    if not argumentos.strip():
        return _listar(account_id, user_id)
    return _pedir(telefone, argumentos, user_id, account_id)


def _concluir(telefone: str, account_id, user_id, itens: list[Item], nao_registrar: set[date]) -> str:
    _salvar(account_id, user_id, itens, nao_registrar)
    limpar_estado(telefone)
    salvos = [i for i in itens if i.valor > 0]
    tirados = [i for i in itens if i.valor == 0]
    partes = []
    if salvos:
        partes.append("renda esperada salva (" + ", ".join(mes_e_ano(i.mes) for i in salvos) + ")")
    if tirados:
        partes.append("valor tirado de " + ", ".join(mes_e_ano(i.mes) for i in tirados))
    registradas = [i for i in salvos if i.recebido and i.mes not in nao_registrar]
    if registradas:
        partes.append("entrada registrada em " + ", ".join(f"{i.data_recebimento:%d/%m/%Y}" for i in registradas))
    return "Pronto: " + "; ".join(partes) + "."


def _pergunta_repetidas(repetidas: list[Item]) -> Resposta:
    linhas = [f"• {formatar_reais(i.valor)} em {mes_e_ano(i.mes)}" for i in repetidas]
    return Resposta(
        "Você já tem uma entrada do mesmo valor no mês:\n" + "\n".join(linhas)
        + "\nRegistrar de novo contaria a renda duas vezes. Registrar mesmo assim?",
        BOTOES_DUPLICADA,
    )


def continuar_renda(telefone: str, dados: dict, texto: str) -> str | Resposta:
    user_id, account_id = conta_do_usuario(telefone)
    passo = dados.get("passo")

    if passo == "aguardando":
        return _pedir(telefone, texto, user_id, account_id)

    itens = [Item.do_estado(i) for i in dados["itens"]]

    if passo == "repetida":
        escolha = normalizar(texto).strip(" .!")
        if escolha in ("registrar", "sim", "s"):
            nao_registrar: set[date] = set()
        elif escolha in ("so a renda", "so renda", "nao", "n", "cancelar"):
            nao_registrar = {i.mes for i in _repetidas(account_id, user_id, itens)}
        else:
            return _pergunta_repetidas(_repetidas(account_id, user_id, itens))
        return _concluir(telefone, account_id, user_id, itens, nao_registrar)

    # passo "confirmar"
    if eh_sim(texto):
        repetidas = _repetidas(account_id, user_id, itens)
        if repetidas:
            salvar_estado(telefone, ESTADO, {**dados, "passo": "repetida"})
            return _pergunta_repetidas(repetidas)
        return _concluir(telefone, account_id, user_id, itens, set())
    if eh_nao(texto) or normalizar(texto).strip(" .!") == "corrigir":
        salvar_estado(telefone, ESTADO, {"passo": "aguardando"})
        return "Mande de novo, sem o /renda. Ex.: outubro 5000, novembro 4000"
    resposta = _pergunta(dados)
    resposta.texto = "Responda Sim ou Corrigir.\n" + resposta.texto
    return resposta
