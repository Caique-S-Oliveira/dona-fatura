"""/objetivos: metas de poupança com valor e prazo, e aportes ("guardei 200 viagem")."""
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app import financas
from app.comandos.cadastro import conta_do_usuario
from app.comandos.categorias import chave
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import eh_nao, eh_sim, formatar_reais, ler_numero, normalizar
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "objetivo"
BOTOES = ("Sim", "Não")
FORMATO = (
    "Para criar: /objetivos novo NOME VALOR PRAZO\n"
    "Ex.: /objetivos novo Viagem 5000 12/2026 (prazo mm/aaaa ou dd/mm/aaaa)\n"
    "Para guardar: guardei 200 viagem\n"
    "Editar ou excluir: toque num item em /objetivos, ou /objetivos editar viagem valor 4000"
)
SEM_OBJETIVOS = "Você ainda não tem objetivos.\n" + FORMATO

# "guardei 200 viagem", "guardei R$ 200 na viagem", "juntei 50 reais para a reserva"
FRASE_APORTE = re.compile(
    r"^\s*(?:eu\s+)?(?:guardei|poupei|juntei|separei)\s+(?:r\$\s*)?(?P<valor>\d[\d.,]*)"
    r"(?:\s*(?:reais|real|conto|contos))?"
    r"(?:\s+(?:(?:no|na|pro|pra|para|em|de|do|da|ao|a)\s+)?(?:objetivo\s+)?(?P<nome>.+?))?\s*$",
    re.IGNORECASE,
)
ARTIGOS = {"a", "o", "as", "os", "meu", "minha"}

ESTADO_GERIR = "objetivo_gerir"
PREFIXO = "obj:"  # id das linhas da lista
BOTOES_ITEM = ("Editar", "Excluir")
BOTOES_CAMPO = ("Nome", "Valor", "Prazo")
CAMPOS = {"nome": "nome", "valor": "valor", "prazo": "prazo"}
PEDIDO = {
    "nome": "Qual o novo nome? (até 40 letras)",
    "valor": "Qual o novo valor da meta? Ex.: 4000",
    "prazo": "Qual o novo prazo? Ex.: 12/2026 ou 15/03/2027",
}


@dataclass
class Objetivo:
    id: str
    nome: str
    meta: Decimal
    prazo: date
    guardado: Decimal

    @property
    def falta(self) -> Decimal:
        return max(self.meta - self.guardado, Decimal("0"))


# ---------- regras (sem banco) ----------

def ler_prazo(texto: str) -> date | None:
    """"12/2026" -> 31/12/2026; "15/03/2027" -> 15/03/2027. None se não for uma data."""
    achado = re.fullmatch(r"(?:(\d{1,2})/)?(\d{1,2})/(\d{4})", texto.strip())
    if achado is None:
        return None
    dia, mes, ano = achado.groups()
    try:
        if dia is None:
            return financas.ultimo_dia_do_mes(date(int(ano), int(mes), 1))
        return date(int(ano), int(mes), int(dia))
    except ValueError:
        return None


def ler_novo(argumentos: str, hoje: date) -> tuple[str, Decimal, date] | str:
    """"Viagem 5000 12/2026" -> (nome, valor, prazo). Se der errado, devolve a mensagem de erro."""
    palavras = argumentos.split()
    if len(palavras) < 3:
        return FORMATO
    prazo = ler_prazo(palavras[-1])
    valor = ler_numero(palavras[-2])
    nome = " ".join(palavras[:-2])
    if prazo is None or valor is None or valor <= 0 or not nome:
        return FORMATO
    if prazo <= hoje:
        return "O prazo precisa ser uma data futura."
    return nome[:40], valor, prazo


def ler_aporte(texto: str) -> tuple[Decimal, str] | None:
    """"guardei 200 viagem" -> (200, "viagem"). Sem nome devolve "" (vale se há 1 só objetivo)."""
    achado = FRASE_APORTE.match(texto)
    if achado is None:
        return None
    valor = ler_numero(achado["valor"])
    if valor is None or valor <= 0:
        return None
    return valor, achado["nome"] or ""


def achar_por_nome(itens: list, nome: str):
    """Acha pelo nome (exato, ou um contido no outro). None se não achar ou se houver dúvida."""
    palavras = [p for p in chave(nome).split() if p not in ARTIGOS]
    if not palavras:
        return itens[0] if len(itens) == 1 else None
    procurado = " ".join(palavras)
    exatos = [i for i in itens if chave(i.nome) == procurado]
    if exatos:
        return exatos[0]
    parecidos = [i for i in itens if procurado in chave(i.nome) or chave(i.nome) in procurado]
    return parecidos[0] if len(parecidos) == 1 else None


achar_objetivo = achar_por_nome


def separar_campo(palavras: list[str], campos: dict[str, str]) -> tuple[str, str | None, str]:
    """["viagem", "valor", "4000"] -> ("viagem", "valor", "4000"). Vale a última palavra-campo."""
    for i in range(len(palavras) - 1, -1, -1):
        campo = campos.get(normalizar(palavras[i]))
        if campo:
            return " ".join(palavras[:i]), campo, " ".join(palavras[i + 1:])
    return " ".join(palavras), None, ""


def valor_do_campo(
    campo: str, texto: str, objetivo: Objetivo, objetivos: list[Objetivo], hoje: date
) -> tuple[object, str | None]:
    """Lê o novo nome, valor ou prazo digitado. Devolve (valor, None) ou (None, mensagem de erro)."""
    if campo == "nome":
        nome = " ".join(texto.split())
        if not nome or len(nome) > 40:
            return None, "Mande só o nome, com até 40 letras."
        if any(o.id != objetivo.id and chave(o.nome) == chave(nome) for o in objetivos):
            return None, f"Você já tem um objetivo chamado {nome}."
        return nome, None
    if campo == "valor":
        valor = ler_numero(texto)
        if valor is None or valor <= 0:
            return None, "Mande um valor maior que zero. Ex.: 4000"
        return valor, None
    prazo = ler_prazo(texto)
    if prazo is None:
        return None, "Não entendi o prazo. Ex.: 12/2026 ou 15/03/2027"
    if prazo <= hoje:
        return None, "O prazo precisa ser uma data futura."
    return prazo, None


def descrever(objetivo: Objetivo, hoje: date) -> str:
    """Duas linhas: quanto já tem e quanto falta / quanto guardar por mês."""
    pct = int(min(objetivo.guardado / objetivo.meta, 1) * 100)
    topo = (
        f"🎯 {objetivo.nome}: {formatar_reais(objetivo.guardado)} de "
        f"{formatar_reais(objetivo.meta)} ({pct}%)"
    )
    if objetivo.falta == 0:
        return f"{topo}\n   ✅ Objetivo alcançado!"
    falta = f"Faltam {formatar_reais(objetivo.falta)}"
    if objetivo.prazo < hoje:
        return f"{topo}\n   ⚠️ {falta}, e o prazo ({objetivo.prazo:%d/%m/%Y}) já passou."
    por_mes = financas.guardar_por_mes(objetivo.falta, objetivo.prazo, hoje)
    return f"{topo}\n   {falta} até {objetivo.prazo:%d/%m/%Y}: guarde {formatar_reais(por_mes)} por mês."


# ---------- banco de dados ----------

def listar_objetivos(account_id) -> list[Objetivo]:
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT g.id, g.name, g.target_amount, g.target_date,"
                " COALESCE(SUM(c.amount), 0) AS guardado FROM savings_goals g"
                " LEFT JOIN savings_contributions c ON c.goal_id = g.id"
                " WHERE g.account_id = :conta GROUP BY g.id ORDER BY g.target_date, g.name"
            ),
            {"conta": account_id},
        ).all()
    return [Objetivo(str(l.id), l.name, l.target_amount, l.target_date, l.guardado) for l in linhas]


def _criar(account_id, user_id, nome: str, meta: Decimal, prazo: date) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO savings_goals (account_id, created_by_user_id, name,"
                " normalized_name, target_amount, target_date)"
                " VALUES (:conta, :usuario, :nome, :chave, :meta, :prazo)"
            ),
            {"conta": account_id, "usuario": user_id, "nome": nome,
             "chave": chave(nome), "meta": meta, "prazo": prazo},
        )


def _guardar(account_id, user_id, objetivo_id: str, valor: Decimal, dia: date) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO savings_contributions (goal_id, account_id, created_by_user_id,"
                " amount, contribution_date) VALUES (:objetivo, :conta, :usuario, :valor, :dia)"
            ),
            {"objetivo": objetivo_id, "conta": account_id, "usuario": user_id,
             "valor": valor, "dia": dia},
        )


def atualizar_objetivo(account_id, objetivo_id: str, campo: str, valor) -> None:
    colunas = {"nome": "name", "valor": "target_amount", "prazo": "target_date"}
    atribuicoes = {colunas[campo]: valor}
    if campo == "nome":
        atribuicoes["normalized_name"] = chave(valor)
    sql = ", ".join(f"{coluna} = :{coluna}" for coluna in atribuicoes)  # colunas fixas acima
    with get_engine().begin() as connection:
        connection.execute(
            text(f"UPDATE savings_goals SET {sql} WHERE id = :id AND account_id = :conta"),
            {**atribuicoes, "id": objetivo_id, "conta": account_id},
        )


def excluir_objetivo(account_id, objetivo_id: str, destino_id: str | None = None) -> None:
    """Apaga o objetivo; com destino, o que foi guardado passa para o outro objetivo."""
    with get_engine().begin() as connection:
        if destino_id:
            connection.execute(
                text(
                    "UPDATE savings_contributions SET goal_id = :destino"
                    " WHERE goal_id = :id AND account_id = :conta"
                ),
                {"destino": destino_id, "id": objetivo_id, "conta": account_id},
            )
        connection.execute(  # os aportes que sobrarem saem junto (ON DELETE CASCADE)
            text("DELETE FROM savings_goals WHERE id = :id AND account_id = :conta"),
            {"id": objetivo_id, "conta": account_id},
        )


# ---------- conversa ----------

def _pct(objetivo: Objetivo) -> int:
    return int(min(objetivo.guardado / objetivo.meta, 1) * 100)


def montar_lista(objetivos: list[Objetivo], texto: str) -> Resposta:
    """Lista interativa (no máximo 10 linhas) com um resumo de cada objetivo."""
    linhas = tuple(
        (PREFIXO + o.id, o.nome,
         f"{formatar_reais(o.guardado)} de {formatar_reais(o.meta)} ({_pct(o)}%) · até {o.prazo:%m/%Y}")
        for o in objetivos[:10]
    )
    if len(objetivos) > 10:
        texto += f" (mostrando 10 de {len(objetivos)})"
    return Resposta(texto, lista=linhas, botao_lista="Ver objetivos", titulo_lista="Objetivos")


def _listar(telefone: str, account_id) -> str | Resposta:
    objetivos = listar_objetivos(account_id)
    if not objetivos:
        return SEM_OBJETIVOS
    salvar_estado(telefone, ESTADO_GERIR, {"etapa": "lista"})
    return montar_lista(objetivos, "Seus objetivos. Toque em um para ver, editar ou excluir:")


def _mostrar(telefone: str, objetivo: Objetivo, hoje: date) -> Resposta:
    salvar_estado(telefone, ESTADO_GERIR, {"etapa": "item", "id": objetivo.id})
    return Resposta(descrever(objetivo, hoje), BOTOES_ITEM)


def _pedir_campo(telefone: str, objetivo: Objetivo) -> Resposta:
    salvar_estado(telefone, ESTADO_GERIR, {"etapa": "campo", "id": objetivo.id})
    return Resposta(f"O que você quer editar em {objetivo.nome}?", BOTOES_CAMPO)


def _pedir_exclusao(telefone: str, objetivo: Objetivo, objetivos: list[Objetivo]) -> Resposta:
    """Sem nada guardado: Sim/Não. Com dinheiro guardado: pergunta o que fazer com ele."""
    if objetivo.guardado > 0:
        botoes = (("Mover",) if len(objetivos) > 1 else ()) + ("Só excluir", "Cancelar")
        salvar_estado(telefone, ESTADO_GERIR, {"etapa": "guardado", "id": objetivo.id})
        return Resposta(
            f"{objetivo.nome} tem {formatar_reais(objetivo.guardado)} guardados.\n"
            "Mover: passa o valor para outro objetivo.\n"
            "Só excluir: apaga o objetivo e os registros do que foi guardado.",
            botoes,
        )
    salvar_estado(telefone, ESTADO_GERIR, {"etapa": "excluir", "id": objetivo.id})
    return Resposta(f"Excluir o objetivo {objetivo.nome}?", BOTOES)


def _depois_de_editar(account_id, objetivo_id: str, hoje: date) -> str:
    atual = next((o for o in listar_objetivos(account_id) if o.id == objetivo_id), None)
    return f"Atualizado!\n{descrever(atual, hoje)}" if atual else "Esse objetivo já não existe."


def _editar_ou_excluir(telefone: str, account_id, acao: str, palavras: list[str], hoje: date):
    """/objetivos editar viagem valor 4000 | editar viagem | excluir viagem."""
    objetivos = listar_objetivos(account_id)
    if not objetivos:
        return SEM_OBJETIVOS
    excluir = acao in ("excluir", "apagar", "remover")
    nome, campo, novo = separar_campo(palavras, {} if excluir else CAMPOS)
    objetivo = achar_por_nome(objetivos, nome)
    if objetivo is None:
        return _listar(telefone, account_id)  # não achou (ou há dúvida): escolha na lista
    if excluir:
        return _pedir_exclusao(telefone, objetivo, objetivos)
    if campo is None:
        return _pedir_campo(telefone, objetivo)
    valor, erro = valor_do_campo(campo, novo, objetivo, objetivos, hoje)
    if erro:
        return erro
    atualizar_objetivo(account_id, objetivo.id, campo, valor)
    return _depois_de_editar(account_id, objetivo.id, hoje)


def _pedir_aporte(telefone: str, account_id, valor: Decimal, nome: str) -> str | Resposta:
    objetivos = listar_objetivos(account_id)
    if not objetivos:
        return SEM_OBJETIVOS
    objetivo = achar_objetivo(objetivos, nome)
    if objetivo is None:
        nomes = ", ".join(o.nome for o in objetivos)
        return f"Em qual objetivo? Seus objetivos: {nomes}.\nEx.: guardei 200 {objetivos[0].nome}"
    salvar_estado(telefone, ESTADO, {"acao": "aporte", "objetivo": objetivo.id,
                                     "nome": objetivo.nome, "valor": str(valor)})
    return Resposta(f"Guardar {formatar_reais(valor)} em {objetivo.nome}?", BOTOES)


def comando_objetivos(telefone: str, argumentos: str) -> str | Resposta:
    hoje = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    palavras = argumentos.split()
    if not palavras:
        return _listar(telefone, account_id)
    acao = normalizar(palavras[0])
    resto = " ".join(palavras[1:])
    if acao in ("novo", "nova", "criar", "adicionar"):
        novo = ler_novo(resto, hoje)
        if isinstance(novo, str):
            return novo
        nome, meta, prazo = novo
        if any(chave(o.nome) == chave(nome) for o in listar_objetivos(account_id)):
            return f"Você já tem um objetivo chamado {nome}."
        salvar_estado(telefone, ESTADO, {"acao": "criar", "nome": nome,
                                         "meta": str(meta), "prazo": prazo.isoformat()})
        return Resposta(
            f"Criar o objetivo {nome}: {formatar_reais(meta)} até {prazo:%d/%m/%Y}?", BOTOES
        )
    if acao in ("editar", "alterar", "excluir", "apagar", "remover"):
        return _editar_ou_excluir(telefone, account_id, acao, palavras[1:], hoje)
    if acao in ("guardar", "aporte"):
        aporte = ler_aporte(f"guardei {resto}")
        return _pedir_aporte(telefone, account_id, *aporte) if aporte else FORMATO
    return _listar(telefone, account_id) if acao in ("ver", "listar") else FORMATO


def frase_de_aporte(telefone: str, texto: str) -> str | Resposta | None:
    """"guardei 200 viagem" -> pede confirmação. None se a frase não for de poupança."""
    aporte = ler_aporte(texto)
    if aporte is None:
        return None
    _, account_id = conta_do_usuario(telefone)
    return _pedir_aporte(telefone, account_id, *aporte)


def continuar_objetivo(telefone: str, dados: dict, texto: str) -> str | Resposta:
    if eh_nao(texto):
        limpar_estado(telefone)
        return "Certo, não anotei nada."
    if not eh_sim(texto):
        return Resposta("Responda Sim ou Não.", BOTOES)
    hoje = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    limpar_estado(telefone)
    if dados["acao"] == "criar":
        meta, prazo = Decimal(dados["meta"]), date.fromisoformat(dados["prazo"])
        _criar(account_id, user_id, dados["nome"], meta, prazo)
        novo = Objetivo("", dados["nome"], meta, prazo, Decimal("0"))
        return f"Objetivo criado!\n{descrever(novo, hoje)}"
    valor = Decimal(dados["valor"])
    _guardar(account_id, user_id, dados["objetivo"], valor, hoje)
    objetivo = next((o for o in listar_objetivos(account_id) if o.id == dados["objetivo"]), None)
    if objetivo is None:
        return "Esse objetivo já não existe."
    return f"Guardado: {formatar_reais(valor)}.\n{descrever(objetivo, hoje)}"


def _da_linha(objetivos: list[Objetivo], texto: str) -> Objetivo | None:
    """Objetivo da linha tocada na lista (o id vem como "obj:ID")."""
    if not texto.startswith(PREFIXO):
        return None
    return next((o for o in objetivos if o.id == texto[len(PREFIXO):]), None)


def continuar_gerir(telefone: str, dados: dict, texto: str) -> str | Resposta | None:
    """Lista -> detalhes [Editar] [Excluir] -> campo e novo valor / confirmação.

    Devolve None (e esquece a conversa) se o texto não for uma resposta esperada.
    """
    hoje = financas.hoje()
    _, account_id = conta_do_usuario(telefone)
    objetivos = listar_objetivos(account_id)
    etapa, escolha = dados["etapa"], chave(texto)
    if etapa == "lista":
        alvo = _da_linha(objetivos, texto)
        if alvo is None:
            limpar_estado(telefone)
            return None
        return _mostrar(telefone, alvo, hoje)
    objetivo = next((o for o in objetivos if o.id == dados.get("id")), None)
    if objetivo is None:
        limpar_estado(telefone)
        return "Esse objetivo já não existe."
    if etapa == "item" and escolha == "editar":
        return _pedir_campo(telefone, objetivo)
    if etapa == "item" and escolha == "excluir":
        return _pedir_exclusao(telefone, objetivo, objetivos)
    if etapa == "campo" and escolha in CAMPOS:
        salvar_estado(telefone, ESTADO_GERIR, {"etapa": "novo", "id": objetivo.id, "campo": escolha})
        return PEDIDO[escolha]
    if etapa == "novo":
        if eh_nao(texto):
            limpar_estado(telefone)
            return "Certo, não alterei nada."
        valor, erro = valor_do_campo(dados["campo"], texto, objetivo, objetivos, hoje)
        if erro:
            return erro
        atualizar_objetivo(account_id, objetivo.id, dados["campo"], valor)
        limpar_estado(telefone)
        return _depois_de_editar(account_id, objetivo.id, hoje)
    if etapa == "excluir" and (eh_sim(texto) or eh_nao(texto)):
        limpar_estado(telefone)
        if eh_nao(texto):
            return "Certo, mantive o objetivo."
        excluir_objetivo(account_id, objetivo.id)
        return f"Pronto, excluí o objetivo {objetivo.nome}."
    outros = [o for o in objetivos if o.id != objetivo.id]
    if etapa == "guardado" and escolha == "mover" and outros:
        salvar_estado(telefone, ESTADO_GERIR, {"etapa": "destino", "id": objetivo.id})
        return montar_lista(outros, f"Para qual objetivo mover {formatar_reais(objetivo.guardado)}?")
    if etapa == "guardado" and escolha == "cancelar":
        limpar_estado(telefone)
        return "Certo, mantive o objetivo."
    if etapa == "guardado" and escolha == "so excluir":
        limpar_estado(telefone)
        excluir_objetivo(account_id, objetivo.id)
        return f"Pronto, excluí {objetivo.nome} e os registros dos {formatar_reais(objetivo.guardado)} guardados."
    if etapa == "destino":
        destino = _da_linha(objetivos, texto)
        if destino is not None and destino.id != objetivo.id:
            limpar_estado(telefone)
            excluir_objetivo(account_id, objetivo.id, destino.id)
            return (
                f"Pronto, movi {formatar_reais(objetivo.guardado)} para {destino.nome}"
                f" e excluí {objetivo.nome}."
            )
    limpar_estado(telefone)
    return None
