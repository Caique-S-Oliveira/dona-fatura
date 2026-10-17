"""/sair_casal: separa o casal em duas contas individuais, cada uma com sua cópia do histórico.

Regras da separação (a conta do casal é substituída por duas contas novas):
- gastos/contas/parcelas "meu" e metas individuais ficam só com o dono (a meta individual
  vira a meta da conta individual dele);
- o que é do casal (histórico "conjunto", categorias, regras aprendidas, metas do casal,
  objetivos de poupança) é copiado para os dois;
- o que o ex-parceiro registrou no histórico conjunto passa a constar como registro de
  quem ficou com a cópia (o banco exige que o autor seja membro da conta).
"""
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.comandos.cadastro import conta_do_usuario
from app.comandos.casal import MEMBROS_NO_CASAL, SEM_NOME, _membros
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import eh_nao, eh_sim
from app.comandos.resposta import Resposta
from app.db import get_engine

logger = logging.getLogger(__name__)

ESTADO = "sair_casal"
BOTOES = ("Sim", "Não")
MSG_SEM_CASAL = "Você não está em um casal. Mande /casal para criar um."
MSG_JA_SAIU = "O casal já foi desfeito. Mande /casal para criar outro."


@dataclass
class Separacao:
    nome_de_quem_saiu: str
    parceiro_id: str
    parceiro_telefone: str
    parceiro_nome: str


def _novo_id() -> str:
    return str(uuid.uuid4())


def _linhas(connection: Connection, comando: str, conta) -> list:
    return connection.execute(text(comando), {"a": conta}).mappings().all()


def _inserir(connection: Connection, tabela: str, valores: dict) -> None:
    colunas = ", ".join(valores)
    parametros = ", ".join(f":{coluna}" for coluna in valores)
    connection.execute(text(f"INSERT INTO {tabela} ({colunas}) VALUES ({parametros})"), valores)


def _copiar_dados(connection: Connection, antiga, nova: dict[str, str]) -> None:
    """Copia os dados da conta do casal para as contas novas. `nova`: usuário -> conta nova."""
    usuarios = list(nova)

    def destinos(escopo: str, criador) -> list[str]:
        return usuarios if escopo == "conjunto" else [str(criador)]

    def autor(criador, usuario: str) -> str:
        return str(criador) if str(criador) == usuario else usuario

    categorias: dict[tuple[str, str], str] = {}
    for l in _linhas(connection, "SELECT id, name, normalized_name, type, is_default,"
                     " created_by_user_id, created_at FROM categories WHERE account_id = :a", antiga):
        for u in usuarios:
            categorias[(u, str(l["id"]))] = novo = _novo_id()
            _inserir(connection, "categories", {
                "id": novo, "account_id": nova[u], "name": l["name"],
                "normalized_name": l["normalized_name"], "type": l["type"],
                "is_default": l["is_default"], "created_at": l["created_at"],
                "created_by_user_id": u if str(l["created_by_user_id"]) == u else None})

    for l in _linhas(connection, "SELECT category_id, normalized_payee, created_at"
                     " FROM classification_rules WHERE account_id = :a", antiga):
        for u in usuarios:
            _inserir(connection, "classification_rules", {
                "id": _novo_id(), "account_id": nova[u], "created_by_user_id": u,
                "category_id": categorias[(u, str(l["category_id"]))],
                "normalized_payee": l["normalized_payee"], "created_at": l["created_at"]})

    # Metas: as do casal vão para os dois; a meta individual de um tipo vence a do casal do mesmo
    # tipo, porque a conta nova é individual e só pode ter uma meta por tipo.
    metas: dict[str, dict[str, tuple]] = {u: {} for u in usuarios}
    linhas_metas = _linhas(connection, "SELECT member_user_id, type, value_type, value"
                           " FROM goals WHERE account_id = :a", antiga)
    for l in sorted(linhas_metas, key=lambda l: l["member_user_id"] is not None):
        donos = usuarios if l["member_user_id"] is None else [str(l["member_user_id"])]
        for u in donos:
            metas[u][l["type"]] = (l["value_type"], l["value"])
    for u, por_tipo in metas.items():
        for tipo, (formato, valor) in por_tipo.items():
            _inserir(connection, "goals", {"id": _novo_id(), "account_id": nova[u],
                                           "member_user_id": None, "type": tipo,
                                           "value_type": formato, "value": valor})

    recorrentes: dict[tuple[str, str], str] = {}
    for l in _linhas(connection, "SELECT id, created_by_user_id, category_id, payee, amount,"
                     " frequency, next_due_date, scope, is_active, created_at"
                     " FROM recurring_transactions WHERE account_id = :a", antiga):
        for u in destinos(l["scope"], l["created_by_user_id"]):
            recorrentes[(u, str(l["id"]))] = novo = _novo_id()
            _inserir(connection, "recurring_transactions", {
                "id": novo, "account_id": nova[u],
                "created_by_user_id": autor(l["created_by_user_id"], u),
                "category_id": categorias.get((u, str(l["category_id"]))),
                "payee": l["payee"], "amount": l["amount"], "frequency": l["frequency"],
                "next_due_date": l["next_due_date"], "scope": l["scope"],
                "is_active": l["is_active"], "created_at": l["created_at"]})

    for l in _linhas(connection, "SELECT created_by_user_id, category_id, recurring_transaction_id,"
                     " transaction_type, amount, description, payee, transaction_date, scope,"
                     " source, created_at FROM transactions"
                     " WHERE account_id = :a AND voided_at IS NULL", antiga):
        for u in destinos(l["scope"], l["created_by_user_id"]):
            _inserir(connection, "transactions", {
                "id": _novo_id(), "account_id": nova[u],
                "created_by_user_id": autor(l["created_by_user_id"], u),
                "category_id": categorias.get((u, str(l["category_id"]))),
                "recurring_transaction_id": recorrentes.get((u, str(l["recurring_transaction_id"]))),
                "transaction_type": l["transaction_type"], "amount": l["amount"],
                "description": l["description"], "payee": l["payee"],
                "transaction_date": l["transaction_date"], "scope": l["scope"],
                "source": l["source"], "created_at": l["created_at"]})

    for l in _linhas(connection, "SELECT created_by_user_id, description, installment_amount,"
                     " total_installments, first_due_date, due_day, scope, created_at"
                     " FROM installments WHERE account_id = :a", antiga):
        for u in destinos(l["scope"], l["created_by_user_id"]):
            _inserir(connection, "installments", {
                "id": _novo_id(), "account_id": nova[u],
                "created_by_user_id": autor(l["created_by_user_id"], u),
                "description": l["description"], "installment_amount": l["installment_amount"],
                "total_installments": l["total_installments"],
                "first_due_date": l["first_due_date"], "due_day": l["due_day"],
                "scope": l["scope"], "created_at": l["created_at"]})

    objetivos: dict[tuple[str, str], str] = {}
    for l in _linhas(connection, "SELECT id, created_by_user_id, name, normalized_name,"
                     " target_amount, target_date, created_at FROM savings_goals"
                     " WHERE account_id = :a", antiga):
        for u in usuarios:  # objetivos de poupança não têm "meu": ficam com os dois
            objetivos[(u, str(l["id"]))] = novo = _novo_id()
            _inserir(connection, "savings_goals", {
                "id": novo, "account_id": nova[u],
                "created_by_user_id": autor(l["created_by_user_id"], u), "name": l["name"],
                "normalized_name": l["normalized_name"], "target_amount": l["target_amount"],
                "target_date": l["target_date"], "created_at": l["created_at"]})
    for l in _linhas(connection, "SELECT goal_id, created_by_user_id, amount, contribution_date,"
                     " created_at FROM savings_contributions WHERE account_id = :a", antiga):
        for u in usuarios:
            _inserir(connection, "savings_contributions", {
                "id": _novo_id(), "account_id": nova[u], "goal_id": objetivos[(u, str(l["goal_id"]))],
                "created_by_user_id": autor(l["created_by_user_id"], u), "amount": l["amount"],
                "contribution_date": l["contribution_date"], "created_at": l["created_at"]})


def separar_casal(user_id, account_id) -> Separacao | None:
    """Troca a conta do casal por duas contas individuais, tudo numa transação só.

    Devolve None se o casal já não existe. Se qualquer passo falhar, nada muda.
    """
    with get_engine().begin() as connection:
        # Trava a conta: se os dois confirmarem ao mesmo tempo, só o primeiro separa.
        travou = connection.execute(
            text("UPDATE accounts SET invitation_code = NULL WHERE id = :a AND mode = 'couple'"
                 " RETURNING id"), {"a": account_id}).first()
        membros = connection.execute(
            text("SELECT m.user_id, m.expected_income, u.phone_number, u.display_name"
                 " FROM members m JOIN users u ON u.id = m.user_id WHERE m.account_id = :a"),
            {"a": account_id}).all()
        if travou is None or len(membros) != MEMBROS_NO_CASAL:
            return None
        nova: dict[str, str] = {}
        for m in membros:
            usuario = str(m.user_id)
            nova[usuario] = _novo_id()
            _inserir(connection, "accounts", {"id": nova[usuario], "owner_user_id": usuario})
            _inserir(connection, "members", {"account_id": nova[usuario], "user_id": usuario,
                                             "role": "owner", "expected_income": m.expected_income})
        _copiar_dados(connection, account_id, nova)
        connection.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": account_id})
    eu = next(m for m in membros if str(m.user_id) == str(user_id))
    outro = next(m for m in membros if str(m.user_id) != str(user_id))
    return Separacao(eu.display_name or SEM_NOME, str(outro.user_id), outro.phone_number,
                     outro.display_name or SEM_NOME)


# ---------- aviso ao parceiro ----------

def guardar_aviso(user_id, mensagem: str) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text("INSERT INTO pending_notices (user_id, message) VALUES (:u, :m)"),
            {"u": user_id, "m": mensagem})


def pegar_avisos(telefone: str) -> list[str]:
    """Avisos guardados para este número (e já os apaga, para chegarem uma vez só)."""
    with get_engine().begin() as connection:
        linhas = connection.execute(
            text("SELECT n.id, n.message FROM pending_notices n JOIN users u ON u.id = n.user_id"
                 " WHERE u.phone_number = :t ORDER BY n.created_at"), {"t": telefone}).all()
        for linha in linhas:
            connection.execute(text("DELETE FROM pending_notices WHERE id = :i"), {"i": linha.id})
    return [linha.message for linha in linhas]


def avisar_parceiro(separacao: Separacao) -> bool:
    """Manda o aviso na hora. Fora da janela de 24h do WhatsApp isso falha: então o aviso fica
    guardado e chega na próxima vez que o parceiro falar com o bot. Devolve True se enviou."""
    from app import whatsapp  # import tardio: o módulo whatsapp importa os comandos

    mensagem = (
        f"{separacao.nome_de_quem_saiu} saiu do casal. Agora cada um tem sua conta: "
        "você ficou com seus gastos \"meu\", suas metas individuais e uma cópia do histórico "
        "e das metas do casal. Para formar outro casal: /casal ou /entrar CÓDIGO."
    )
    try:
        whatsapp.send_text(separacao.parceiro_telefone, mensagem)
        return True
    except Exception:
        logger.warning("Não consegui avisar o parceiro agora; o aviso fica guardado.")
        guardar_aviso(separacao.parceiro_id, mensagem)
        return False


# ---------- conversa ----------

def _pergunta(nome: str) -> Resposta:
    return Resposta(
        f"Sair do casal com {nome}?\n"
        "Cada um fica com seus gastos \"meu\" e metas individuais; os dois ficam com uma cópia "
        f"do histórico e das metas do casal. {nome} será avisado(a).",
        BOTOES,
    )


def comando_sair_casal(telefone: str, argumentos: str) -> str | Resposta:
    user_id, account_id = conta_do_usuario(telefone)
    membros = _membros(account_id)
    if len(membros) < MEMBROS_NO_CASAL:
        return MSG_SEM_CASAL
    parceiro = next(m for m in membros if str(m.user_id) != str(user_id))
    salvar_estado(telefone, ESTADO, {})
    return _pergunta(parceiro.display_name or SEM_NOME)


def continuar_sair_casal(telefone: str, dados: dict, texto: str) -> str | Resposta:
    if eh_nao(texto):
        limpar_estado(telefone)
        return "Certo, vocês continuam em casal."
    user_id, account_id = conta_do_usuario(telefone)
    if not eh_sim(texto):
        parceiro = next((m for m in _membros(account_id) if str(m.user_id) != str(user_id)), None)
        resposta = _pergunta((parceiro.display_name if parceiro else None) or SEM_NOME)
        resposta.texto = "Toque em Sim ou Não.\n" + resposta.texto
        return resposta
    limpar_estado(telefone)
    separacao = separar_casal(user_id, account_id)
    if separacao is None:
        return MSG_JA_SAIU
    limpar_estado(separacao.parceiro_telefone)  # uma conversa aberta usaria ids da conta que acabou
    avisou = avisar_parceiro(separacao)
    aviso = (f"{separacao.parceiro_nome} foi avisado(a)." if avisou
             else f"Não consegui avisar {separacao.parceiro_nome} agora; aviso quando falar comigo.")
    return (
        "Pronto, você saiu do casal e voltou ao modo individual.\n"
        "Ficaram seus gastos \"meu\", suas metas e uma cópia do histórico e das metas do casal.\n"
        f"{aviso} Para outro casal: /casal ou /entrar CÓDIGO."
    )
