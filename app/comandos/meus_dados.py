"""/meus_dados: envia uma planilha (.xlsx) com tudo o que está guardado sobre a pessoa."""
from sqlalchemy import text

from app import xlsx
from app.comandos.cadastro import conta_do_usuario
from app.comandos.resposta import Resposta
from app.db import get_engine

NOME_ARQUIVO = "meus_dados_dona_fatura.xlsx"

ESCOPO = {"meu": "Meu", "conjunto": "Conjunto"}
TIPO = {"income": "Entrada", "expense": "Saída"}
ORIGEM = {"paystub": "Holerite", "receipt": "Comprovante", "manual": "Texto"}
FORMATO_META = {"amount": "R$", "percentage": "%"}


def _linhas(connection, sql: str, parametros: dict) -> list:
    return list(connection.execute(text(sql), parametros))


def montar_planilha(user_id, account_id) -> bytes:
    """Só entra o que a pessoa pode ver: o que ela criou e o que é conjunto (nunca o "meu" do parceiro)."""
    p = {"conta": account_id, "usuario": user_id}
    with get_engine().connect() as c:
        usuario = c.execute(text(
            "SELECT u.phone_number, u.display_name, u.profile_name, u.created_at, u.lembretes_ativos,"
            " u.privacidade_aceita_em, m.expected_income, a.mode"
            " FROM users u JOIN members m ON m.user_id = u.id AND m.account_id = :conta"
            " JOIN accounts a ON a.id = m.account_id WHERE u.id = :usuario"
        ), p).one()
        transacoes = _linhas(c,
            "SELECT t.transaction_date, t.transaction_type, t.amount, t.payee, t.description, k.name AS categoria,"
            " t.scope, t.source, t.created_at, t.voided_at FROM transactions t"
            " LEFT JOIN categories k ON k.id = t.category_id AND k.account_id = t.account_id"
            " WHERE t.account_id = :conta AND (t.created_by_user_id = :usuario OR t.scope = 'conjunto')"
            " ORDER BY t.transaction_date, t.created_at", p)
        recorrentes = _linhas(c,
            "SELECT r.payee, r.amount, r.frequency, r.next_due_date, k.name AS categoria, r.scope, r.is_active"
            " FROM recurring_transactions r LEFT JOIN categories k ON k.id = r.category_id AND k.account_id = r.account_id"
            " WHERE r.account_id = :conta AND (r.created_by_user_id = :usuario OR r.scope = 'conjunto')"
            " ORDER BY r.payee", p)
        metas = _linhas(c,
            "SELECT type, value_type, value, member_user_id FROM goals"
            " WHERE account_id = :conta AND (member_user_id IS NULL OR member_user_id = :usuario) ORDER BY type", p)
        categorias = _linhas(c,
            "SELECT name, type, is_default FROM categories WHERE account_id = :conta ORDER BY type, name", p)
        regras = _linhas(c,
            "SELECT r.normalized_payee, k.name AS categoria FROM classification_rules r"
            " JOIN categories k ON k.id = r.category_id AND k.account_id = r.account_id"
            " WHERE r.account_id = :conta ORDER BY r.normalized_payee", p)
        objetivos = _linhas(c,
            "SELECT g.name, g.target_amount, g.target_date,"
            " COALESCE((SELECT sum(amount) FROM savings_contributions s WHERE s.goal_id = g.id), 0) AS guardado"
            " FROM savings_goals g WHERE g.account_id = :conta ORDER BY g.name", p)
        aportes = _linhas(c,
            "SELECT s.contribution_date, g.name, s.amount FROM savings_contributions s"
            " JOIN savings_goals g ON g.id = s.goal_id WHERE s.account_id = :conta"
            " ORDER BY s.contribution_date", p)
        parcelas = _linhas(c,
            "SELECT description, installment_amount, total_installments, COALESCE(paid_installments, 0) AS pagas,"
            " first_due_date, due_day, scope FROM installments"
            " WHERE account_id = :conta AND (created_by_user_id = :usuario OR scope = 'conjunto')"
            " ORDER BY description", p)

    em_casal = usuario.mode != "individual"
    resumo = [
        ["Número de WhatsApp", usuario.phone_number],
        ["Nome", usuario.display_name],
        ["Nome do perfil no WhatsApp", usuario.profile_name],
        ["Renda esperada (R$)", usuario.expected_income],
        ["Modo da conta", "Casal" if em_casal else "Individual"],
        ["Cadastro criado em", usuario.created_at],
        ["Aviso de privacidade aceito em", usuario.privacidade_aceita_em],
        ["Lembretes automáticos ligados", usuario.lembretes_ativos],
    ]
    abas = [
        ("Seus dados", ["Campo", "Valor"], resumo),
        ("Transações", ["Data", "Tipo", "Valor (R$)", "Favorecido", "Descrição", "Categoria", "Visibilidade",
                        "Origem", "Registrado em", "Desfeito em"],
         [[t.transaction_date, TIPO.get(t.transaction_type, t.transaction_type), t.amount, t.payee, t.description,
           t.categoria, ESCOPO.get(t.scope, t.scope), ORIGEM.get(t.source, t.source), t.created_at, t.voided_at]
          for t in transacoes]),
        ("Recorrentes", ["Favorecido", "Valor (R$)", "Frequência", "Próximo vencimento", "Categoria",
                         "Visibilidade", "Ativo"],
         [[r.payee, r.amount, r.frequency, r.next_due_date, r.categoria, ESCOPO.get(r.scope, r.scope),
           bool(r.is_active)] for r in recorrentes]),
        ("Metas", ["Tipo", "Formato", "Valor", "De quem"],
         [[m.type, FORMATO_META.get(m.value_type, m.value_type), m.value,
           "Só minha" if m.member_user_id else "Da conta"] for m in metas]),
        ("Categorias", ["Nome", "Tipo", "Padrão"], [[k.name, k.type, bool(k.is_default)] for k in categorias]),
        ("Regras aprendidas", ["Favorecido", "Categoria"], [[r.normalized_payee, r.categoria] for r in regras]),
        ("Objetivos", ["Nome", "Valor alvo (R$)", "Prazo", "Guardado (R$)"],
         [[o.name, o.target_amount, o.target_date, o.guardado] for o in objetivos]),
        ("Aportes", ["Data", "Objetivo", "Valor (R$)"], [[a.contribution_date, a.name, a.amount] for a in aportes]),
        ("Parcelas", ["Descrição", "Valor da parcela (R$)", "Total de parcelas", "Pagas", "Primeiro vencimento",
                      "Dia do vencimento", "Visibilidade"],
         [[x.description, x.installment_amount, x.total_installments, x.pagas, x.first_due_date,
           x.due_day, ESCOPO.get(x.scope, x.scope)] for x in parcelas]),
    ]
    if em_casal:
        abas.append(("Aviso", ["Observação"], [[
            "Gastos marcados como \"meu\" pelo seu parceiro não aparecem aqui. "
            "A planilha traz os seus registros e os conjuntos."]]))
    return xlsx.montar(abas)


def comando_meus_dados(telefone: str, argumentos: str) -> str | Resposta:
    user_id, account_id = conta_do_usuario(telefone)
    return Resposta(
        "📎 Aqui está tudo o que guardo sobre você, em planilha. "
        "Para apagar, mande /apagar_meus_dados.",
        documento=(NOME_ARQUIVO, montar_planilha(user_id, account_id)),
    )
