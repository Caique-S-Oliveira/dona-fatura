"""/parcelas: compras parceladas. As parcelas que ainda vencem entram na previsão do mês."""
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app import financas
from app.comandos.cadastro import conta_do_usuario
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import eh_nao, eh_sim, formatar_reais, ler_numero, normalizar
from app.comandos.gasto import separar_escopo
from app.comandos.objetivos import achar_por_nome, separar_campo
from app.comandos.resposta import Resposta
from app.db import get_engine

ESTADO = "parcela"
ESTADO_GERIR = "parcela_gerir"
PREFIXO = "par:"  # id das linhas da lista
BOTOES = ("Sim", "Não")
BOTOES_ITEM = ("Editar", "Excluir")
BOTOES_CAMPO = ("Valor", "Nº de parcelas", "Pagas")
CAMPOS = {"valor": "valor", "parcelas": "parcelas", "pagas": "pagas", "pago": "pagas"}
ESCOLHA_CAMPO = {"valor": "valor", "no de parcelas": "parcelas", "n de parcelas": "parcelas", "pagas": "pagas"}
FORMATO = (
    "Para cadastrar: /parcelas nova NOME VALOR_DA_PARCELA NUMERO_x\n"
    "Ex.: /parcelas nova Geladeira 250 10x\n"
    "Opcional: dia 20 (vencimento), pagas 3 (já pagas), meu (só você vê)\n"
    "Editar ou excluir: toque num item em /parcelas, ou /parcelas editar geladeira valor 300"
)
SEM_PARCELAS = "Você não tem parcelas pendentes.\n" + FORMATO
NOVOS = ("nova", "novo", "criar", "adicionar", "add")


def ler_nova(argumentos: str, hoje: date) -> tuple[financas.Parcelamento, str, int] | str:
    """"Geladeira 250 10x dia 20 pagas 3 meu" -> (parcelamento, escopo, pagas). Erro -> mensagem."""
    descricao, escopo = separar_escopo(argumentos)
    palavras = descricao.split()
    total = dia = None
    pagas = 0
    livres: list[str] = []  # nome e valor, na ordem em que apareceram
    i = 0
    while i < len(palavras):
        palavra = normalizar(palavras[i])
        seguinte = palavras[i + 1] if i + 1 < len(palavras) else ""
        if re.fullmatch(r"\d{1,3}x", palavra):
            total = int(palavra[:-1])
        elif palavra == "dia" and seguinte.isdigit():
            dia, i = int(seguinte), i + 1
        elif palavra in ("pagas", "paga", "pagos") and seguinte.isdigit():
            pagas, i = int(seguinte), i + 1
        elif palavra != "r$":
            livres.append(palavras[i])
        i += 1
    # O valor é o último número solto; o resto é o nome (ex.: "iphone 15 250 10x").
    posicao = next((n for n in range(len(livres) - 1, -1, -1) if ler_numero(livres[n])), None)
    if total is None or posicao is None or posicao == 0:
        return FORMATO
    valor = ler_numero(livres[posicao])
    nome = " ".join(livres[:posicao] + livres[posicao + 1:])
    if not nome or valor <= 0 or not 1 <= total <= 360:
        return FORMATO
    if dia is not None and not 1 <= dia <= 31:
        return "O dia de vencimento precisa estar entre 1 e 31."
    if pagas >= total:
        return "Se todas as parcelas já foram pagas, não precisa cadastrar."
    dia = dia or hoje.day
    proximo = financas.proximo_dia(dia, hoje)
    primeiro = financas.somar_meses(proximo, -pagas, dia)
    return financas.Parcelamento(nome[:60], valor, total, primeiro, dia), escopo, pagas


def descrever(p: financas.Parcelamento, hoje: date) -> str:
    """"📦 Geladeira: parcela 3/10 de R$ 250,00 — faltam 7 (R$ 1.750,00), próxima 20/11"."""
    pagas = p.pagas(hoje)
    return (
        f"📦 {p.nome}: parcela {min(pagas + 1, p.total)}/{p.total} de {formatar_reais(p.valor)}"
        f" — faltam {p.restantes(hoje)} ({formatar_reais(p.falta_pagar(hoje))}),"
        f" próxima {p.proximo_vencimento(hoje):%d/%m}"
    )


def pendentes(parcelas: list[financas.Parcelamento], hoje: date) -> list[financas.Parcelamento]:
    """Só as que ainda têm parcela a pagar, da que vence primeiro para a última."""
    return sorted(
        (p for p in parcelas if p.restantes(hoje)), key=lambda p: p.proximo_vencimento(hoje)
    )


def montar_lista(parcelas: list[financas.Parcelamento], hoje: date) -> str | Resposta:
    """Lista interativa (no máximo 10 linhas); o texto traz os totais."""
    abertas = pendentes(parcelas, hoje)
    if not abertas:
        return SEM_PARCELAS
    falta = sum((p.falta_pagar(hoje) for p in abertas), Decimal("0"))
    neste_mes = financas.valor_parcelas_a_vencer(abertas, hoje)
    texto = (
        f"Falta pagar {formatar_reais(falta)} no total; ainda vence {formatar_reais(neste_mes)} este mês.\n"
        "Toque em uma para ver, editar ou excluir:"
    )
    if len(abertas) > 10:
        texto += f" (mostrando 10 de {len(abertas)})"
    linhas = tuple(
        (PREFIXO + p.id, p.nome,
         f"{min(p.pagas(hoje) + 1, p.total)}/{p.total} de {formatar_reais(p.valor)} · próxima {p.proximo_vencimento(hoje):%d/%m}")
        for p in abertas[:10]
    )
    return Resposta(texto, lista=linhas, botao_lista="Ver parcelas", titulo_lista="Parcelas")


def listar_parcelas(account_id, user_id) -> list[financas.Parcelamento]:
    """Parcelas que o usuário pode ver (as "meu" do parceiro ficam de fora)."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text(
                "SELECT description, installment_amount, total_installments, first_due_date,"
                " due_day, id FROM installments WHERE account_id = :conta"
                " AND (scope = 'conjunto' OR created_by_user_id = :usuario)"
                " ORDER BY created_at"
            ),
            {"conta": account_id, "usuario": user_id},
        ).all()
    return [financas.Parcelamento(l[0], l[1], l[2], l[3], l[4], str(l[5])) for l in linhas]


# ---------- editar e excluir ----------

def valor_do_campo(campo: str, texto: str, p: financas.Parcelamento, hoje: date) -> tuple[object, str | None]:
    """Lê o novo valor, nº de parcelas ou nº de pagas. Devolve (valor, None) ou (None, erro)."""
    if campo == "valor":
        valor = ler_numero(texto)
        if valor is None or valor <= 0:
            return None, "Mande um valor maior que zero. Ex.: 300"
        return valor, None
    numero = texto.strip().lower().rstrip("x")
    if not numero.isdigit():
        return None, "Mande só o número. Ex.: 12"
    numero = int(numero)
    if campo == "parcelas":
        if not 1 <= numero <= 360:
            return None, "O número de parcelas precisa estar entre 1 e 360."
        if numero <= p.pagas(hoje):
            return None, f"Já foram pagas {p.pagas(hoje)}; o total precisa ser maior. Para encerrar, exclua."
        return numero, None
    if numero >= p.total:
        return None, f"São {p.total} parcelas; as pagas precisam ser de 0 a {p.total - 1}."
    return numero, None


def atualizar_parcela(account_id, p: financas.Parcelamento, campo: str, valor, hoje: date) -> None:
    if campo == "pagas":
        # a próxima parcela é a do próximo vencimento; as anteriores contam como pagas
        coluna, valor = "first_due_date", financas.somar_meses(financas.proximo_dia(p.dia, hoje), -valor, p.dia)
    else:
        coluna = {"valor": "installment_amount", "parcelas": "total_installments"}[campo]
    with get_engine().begin() as connection:
        connection.execute(
            text(f"UPDATE installments SET {coluna} = :valor WHERE id = :id AND account_id = :conta"),
            {"valor": valor, "id": p.id, "conta": account_id},
        )


def excluir_parcela(account_id, parcela_id: str) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text("DELETE FROM installments WHERE id = :id AND account_id = :conta"),
            {"id": parcela_id, "conta": account_id},
        )


def _listar(telefone: str, account_id, user_id, hoje: date) -> str | Resposta:
    """Mostra a lista e fica esperando o toque num item."""
    lista = montar_lista(listar_parcelas(account_id, user_id), hoje)
    if isinstance(lista, Resposta):
        salvar_estado(telefone, ESTADO_GERIR, {"etapa": "lista"})
    return lista


def _detalhes(p: financas.Parcelamento, hoje: date) -> str:
    return (
        f"{descrever(p, hoje)}\n"
        f"Total {formatar_reais(p.valor * p.total)}; {p.pagas(hoje)} de {p.total} já pagas."
    )


def _mostrar(telefone: str, p: financas.Parcelamento, hoje: date) -> Resposta:
    salvar_estado(telefone, ESTADO_GERIR, {"etapa": "item", "id": p.id})
    return Resposta(_detalhes(p, hoje), BOTOES_ITEM)


def _pedir_campo(telefone: str, p: financas.Parcelamento) -> Resposta:
    salvar_estado(telefone, ESTADO_GERIR, {"etapa": "campo", "id": p.id})
    return Resposta(f"O que você quer editar em {p.nome}?", BOTOES_CAMPO)


def _pedir_exclusao(telefone: str, p: financas.Parcelamento) -> Resposta:
    salvar_estado(telefone, ESTADO_GERIR, {"etapa": "excluir", "id": p.id})
    return Resposta(f"Excluir a compra parcelada {p.nome}? Ela sai da previsão.", BOTOES)


def _depois_de_editar(account_id, user_id, parcela_id: str, hoje: date) -> str:
    atual = next((p for p in listar_parcelas(account_id, user_id) if p.id == parcela_id), None)
    if atual is None:
        return "Essa parcela já não existe."
    return f"Atualizado! A previsão já usa o novo valor.\n{_detalhes(atual, hoje)}"


def _editar_ou_excluir(telefone: str, account_id, user_id, acao: str, palavras: list[str], hoje: date):
    """/parcelas editar geladeira valor 300 | editar geladeira | excluir geladeira."""
    parcelas = listar_parcelas(account_id, user_id)
    if not parcelas:
        return SEM_PARCELAS
    excluir = acao in ("excluir", "apagar", "remover")
    nome, campo, novo = separar_campo(palavras, {} if excluir else CAMPOS)
    p = achar_por_nome(parcelas, nome)
    if p is None:
        return _listar(telefone, account_id, user_id, hoje)  # não achou (ou há dúvida): escolha na lista
    if excluir:
        return _pedir_exclusao(telefone, p)
    if campo is None:
        return _pedir_campo(telefone, p)
    valor, erro = valor_do_campo(campo, novo, p, hoje)
    if erro:
        return erro
    atualizar_parcela(account_id, p, campo, valor, hoje)
    return _depois_de_editar(account_id, user_id, p.id, hoje)


def _gravar(account_id, user_id, p: financas.Parcelamento, escopo: str) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO installments (account_id, created_by_user_id, description,"
                " installment_amount, total_installments, first_due_date, due_day, scope)"
                " VALUES (:conta, :usuario, :nome, :valor, :total, :primeiro, :dia, :escopo)"
            ),
            {"conta": account_id, "usuario": user_id, "nome": p.nome, "valor": p.valor,
             "total": p.total, "primeiro": p.primeiro_vencimento, "dia": p.dia, "escopo": escopo},
        )


def comando_parcelas(telefone: str, argumentos: str) -> str | Resposta:
    hoje = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    palavras = argumentos.split()
    if not palavras:
        return _listar(telefone, account_id, user_id, hoje)
    acao = normalizar(palavras[0])
    if acao in ("editar", "alterar", "excluir", "apagar", "remover"):
        return _editar_ou_excluir(telefone, account_id, user_id, acao, palavras[1:], hoje)
    if acao not in NOVOS:
        return FORMATO
    nova = ler_nova(" ".join(palavras[1:]), hoje)
    if isinstance(nova, str):
        return nova
    p, escopo, pagas = nova
    salvar_estado(telefone, ESTADO, {
        "nome": p.nome, "valor": str(p.valor), "total": p.total,
        "primeiro": p.primeiro_vencimento.isoformat(), "dia": p.dia, "escopo": escopo,
    })
    extra = f" ({pagas} já paga{'s' if pagas != 1 else ''})" if pagas else ""
    return Resposta(
        f"Cadastrar {p.nome}: {p.total}x de {formatar_reais(p.valor)}{extra}?\n"
        f"Total {formatar_reais(p.valor * p.total)}; próxima parcela em "
        f"{p.proximo_vencimento(hoje):%d/%m/%Y}.",
        BOTOES,
    )


def continuar_parcela(telefone: str, dados: dict, texto: str) -> str | Resposta:
    if eh_nao(texto):
        limpar_estado(telefone)
        return "Certo, não cadastrei."
    if not eh_sim(texto):
        return Resposta("Responda Sim ou Não.", BOTOES)
    user_id, account_id = conta_do_usuario(telefone)
    p = financas.Parcelamento(
        dados["nome"], Decimal(dados["valor"]), dados["total"],
        date.fromisoformat(dados["primeiro"]), dados["dia"],
    )
    _gravar(account_id, user_id, p, dados["escopo"])
    limpar_estado(telefone)
    return f"Anotado! Essas parcelas já entram na previsão do mês.\n{descrever(p, financas.hoje())}"


PEDIDO = {
    "valor": "Qual o novo valor de cada parcela? Ex.: 300",
    "parcelas": "Quantas parcelas são no total? Ex.: 12",
    "pagas": "Quantas parcelas já foram pagas? Ex.: 4",
}


def continuar_gerir(telefone: str, dados: dict, texto: str) -> str | Resposta | None:
    """Lista -> detalhes [Editar] [Excluir] -> campo e novo valor / confirmação.

    Devolve None (e esquece a conversa) se o texto não for uma resposta esperada.
    """
    hoje = financas.hoje()
    user_id, account_id = conta_do_usuario(telefone)
    parcelas = listar_parcelas(account_id, user_id)
    etapa, escolha = dados["etapa"], normalizar(texto).strip(" .!º°").replace("º", "o")
    if etapa == "lista":
        alvo = next((p for p in parcelas if texto == PREFIXO + p.id), None)
        if alvo is None:
            limpar_estado(telefone)
            return None
        return _mostrar(telefone, alvo, hoje)
    p = next((x for x in parcelas if x.id == dados.get("id")), None)
    if p is None:
        limpar_estado(telefone)
        return "Essa parcela já não existe."
    if etapa == "item" and escolha == "editar":
        return _pedir_campo(telefone, p)
    if etapa == "item" and escolha == "excluir":
        return _pedir_exclusao(telefone, p)
    if etapa == "campo" and escolha in ESCOLHA_CAMPO:
        campo = ESCOLHA_CAMPO[escolha]
        salvar_estado(telefone, ESTADO_GERIR, {"etapa": "novo", "id": p.id, "campo": campo})
        return PEDIDO[campo]
    if etapa == "novo":
        if eh_nao(texto):
            limpar_estado(telefone)
            return "Certo, não alterei nada."
        valor, erro = valor_do_campo(dados["campo"], texto, p, hoje)
        if erro:
            return erro
        atualizar_parcela(account_id, p, dados["campo"], valor, hoje)
        limpar_estado(telefone)
        return _depois_de_editar(account_id, user_id, p.id, hoje)
    if etapa == "excluir" and (eh_sim(texto) or eh_nao(texto)):
        limpar_estado(telefone)
        if eh_nao(texto):
            return "Certo, mantive a parcela."
        excluir_parcela(account_id, p.id)
        return f"Pronto, excluí {p.nome}. Ela saiu da previsão."
    limpar_estado(telefone)
    return None
