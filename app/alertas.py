"""Etapa 14: alertas automáticos (rota /cron) e alerta de gasto muito acima do normal.

Regras:
- no máximo 3 alertas por semana (segunda a domingo) por usuário, e nunca repetidos
  (a tabela sent_alerts guarda uma chave por alerta);
- prioridade na rota /cron: (1) resumo semanal, (2) conta/assinatura/parcela vencendo amanhã,
  (3) lembrete após 4 dias sem registros; no máximo 1 alerta por usuário a cada chamada;
- os números vêm do Python; a IA só reescreve o texto (se falhar ou trouxer número novo,
  vale o texto pronto);
- texto comum só vale dentro da janela de 24h do WhatsApp. Fora dela, só modelo (template)
  aprovado, e só se MODELOS_ATIVOS=1; senão o alerta é pulado SEM ser marcado como enviado.
"""
import contextvars
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from app import financas, ia
from app.comandos.diagnostico import _metas_em_reais, _numeros
from app.comandos.formato import formatar_reais
from app.comandos.metas import ler_metas, ler_renda, ler_renda_conjunta
from app.comandos.casal import conta_em_casal
from app.comandos.previsao import MESES
from app.comandos.resumo import montar_resumo
from app.db import get_engine
from app.financas import BRASIL, Parcelamento

logger = logging.getLogger(__name__)

HORA_DO_ENVIO = 10
LIMITE_SEMANAL = 3
# O WhatsApp aceita texto livre até 24h depois da última mensagem do usuário. Deixo 10 min de
# folga para a mensagem não cruzar o limite no caminho.
JANELA = timedelta(hours=24) - timedelta(minutes=10)
DIAS_SEM_REGISTRO = 4

# Gasto muito acima do normal: pelo menos MULTIPLO x a média das compras da categoria nos
# últimos DIAS_DE_HISTORICO dias (com no mínimo MIN_HISTORICO compras) e no mínimo VALOR_MINIMO.
MULTIPLO = Decimal("3")
MIN_HISTORICO = 5
VALOR_MINIMO = Decimal("100")
DIAS_DE_HISTORICO = 90

TIPO_RESUMO = "resumo_semanal"
TIPO_VENCIMENTO = "vencimento"
TIPO_LEMBRETE = "lembrete"
TIPO_GASTO_ALTO = "gasto_alto"

# Modelos (templates) da Meta. O corpo de cada um está em docs/modelos_whatsapp.md.
MODELO_RESUMO = "resumo_semanal"
MODELO_VENCIMENTO = "conta_vencendo_amanha"
MODELO_LEMBRETE = "lembrete_sem_registros"


def modelos_ativos() -> bool:
    return os.getenv("MODELOS_ATIVOS", "0").strip() == "1"


@dataclass
class Alerta:
    tipo: str
    chave: str  # não repete para o mesmo usuário
    fatos: str  # texto pronto, com os números; a IA pode reescrever o tom
    modelo: str  # nome do modelo da Meta (usado fora da janela de 24h)
    parametros: list[str]  # variáveis do modelo: uma linha cada, sem quebra de linha
    inicio: date | None = None
    fim: date | None = None


@dataclass
class Destinatario:
    user_id: str
    account_id: str
    telefone: str


def _curto(user_id) -> str:
    return str(user_id)[:8]  # o log não precisa do telefone inteiro


# ---------- texto final (a IA só escreve) ----------

SISTEMA_ALERTA = (
    "Você é a Dona Fatura, assistente financeira no WhatsApp: direta e objetiva, firme ao avisar "
    "de gasto fora do plano, sem esconder o problema, com um toque de simpatia e sem sermão. "
    "Recebe um alerta com números JÁ CALCULADOS. Reescreva em português do Brasil, em no máximo "
    "5 linhas curtas, mantendo todos os fatos e a mesma ordem. Use SÓ os números, valores e datas "
    "recebidos, exatamente como estão; não calcule, não some, não arredonde, não invente nada."
)


def texto_do_alerta(fatos: str) -> str:
    """A IA reescreve no tom da Dona Fatura; se falhar ou trouxer número novo, vale o texto pronto."""
    escrito = ia.chamar_ia(SISTEMA_ALERTA, fatos, max_tokens=300)
    if escrito is None or not _numeros(escrito) <= _numeros(fatos):
        return fatos
    return escrito


# ---------- janela de 24h e limite semanal ----------

def inicio_da_semana(agora: datetime) -> datetime:
    """Segunda-feira, 00:00 (horário de Brasília)."""
    segunda = agora.astimezone(BRASIL).date() - timedelta(days=agora.astimezone(BRASIL).weekday())
    return datetime(segunda.year, segunda.month, segunda.day, tzinfo=BRASIL)


def dentro_da_janela(ultima_mensagem: datetime | None, agora: datetime) -> bool:
    return ultima_mensagem is not None and agora - ultima_mensagem < JANELA


def _como_datetime(valor) -> datetime | None:
    """O PostgreSQL devolve datetime; guardo a conversão por segurança (e para os testes)."""
    if valor is None or isinstance(valor, datetime):
        return valor
    return datetime.fromisoformat(str(valor))


def ultima_mensagem_do_usuario(telefone: str) -> datetime | None:
    with get_engine().connect() as connection:
        valor = connection.execute(
            text("SELECT MAX(received_at) FROM processed_messages WHERE sender_phone_number = :t"),
            {"t": telefone},
        ).scalar()
    ultima = _como_datetime(valor)
    if ultima is not None and ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=BRASIL)  # sem fuso: assumo Brasília
    return ultima


def enviados_na_semana(user_id, agora: datetime) -> int:
    with get_engine().connect() as connection:
        return connection.execute(
            text("SELECT COUNT(*) FROM sent_alerts WHERE user_id = :u AND sent_at >= :inicio"),
            {"u": user_id, "inicio": inicio_da_semana(agora)},
        ).scalar_one()


def _reservar(destino: Destinatario, alerta: Alerta) -> bool:
    """Marca o alerta como enviado ANTES de mandar (duas chamadas ao mesmo tempo não duplicam).
    False se a chave já existia."""
    with get_engine().begin() as connection:
        resultado = connection.execute(
            text(
                "INSERT INTO sent_alerts (account_id, user_id, alert_type, deduplication_key,"
                " period_start, period_end) VALUES (:conta, :usuario, :tipo, :chave, :inicio, :fim)"
                " ON CONFLICT (account_id, user_id, deduplication_key) DO NOTHING"
            ),
            {"conta": destino.account_id, "usuario": destino.user_id, "tipo": alerta.tipo,
             "chave": alerta.chave, "inicio": alerta.inicio, "fim": alerta.fim},
        )
        return resultado.rowcount == 1


def _desfazer_reserva(destino: Destinatario, alerta: Alerta) -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text("DELETE FROM sent_alerts WHERE account_id = :conta AND user_id = :usuario"
                 " AND deduplication_key = :chave"),
            {"conta": destino.account_id, "usuario": destino.user_id, "chave": alerta.chave},
        )


def _guardar_id_da_mensagem(destino: Destinatario, alerta: Alerta, mensagem_id: str | None) -> None:
    if not mensagem_id:
        return
    with get_engine().begin() as connection:
        connection.execute(
            text("UPDATE sent_alerts SET whatsapp_message_id = :m WHERE account_id = :conta"
                 " AND user_id = :usuario AND deduplication_key = :chave"),
            {"m": mensagem_id, "conta": destino.account_id, "usuario": destino.user_id,
             "chave": alerta.chave},
        )


def ja_enviado(destino: Destinatario, chave: str) -> bool:
    with get_engine().connect() as connection:
        return connection.execute(
            text("SELECT 1 FROM sent_alerts WHERE account_id = :conta AND user_id = :usuario"
                 " AND deduplication_key = :chave"),
            {"conta": destino.account_id, "usuario": destino.user_id, "chave": chave},
        ).first() is not None


# ---------- envio ----------

def enviar_alerta(destino: Destinatario, alerta: Alerta, agora: datetime, ultima: datetime | None) -> str:
    """Tenta enviar. Devolve "texto", "modelo" ou o motivo de não ter enviado.

    Cada resultado vai para o log. Só marca como enviado se o envio deu certo.
    """
    from app import whatsapp  # import tardio: o módulo whatsapp importa os comandos

    em_janela = dentro_da_janela(ultima, agora)
    if not em_janela and not modelos_ativos():
        return "pulado: fora da janela de 24h e modelos desligados"
    if not _reservar(destino, alerta):
        return "pulado: já enviado"
    try:
        if em_janela:
            mensagem_id = whatsapp.send_text(destino.telefone, texto_do_alerta(alerta.fatos))
            canal = "texto"
        else:
            mensagem_id = whatsapp.send_template(destino.telefone, alerta.modelo, alerta.parametros)
            canal = "modelo"
    except Exception:
        logger.exception("Falha ao enviar alerta %s ao usuário %s", alerta.tipo, _curto(destino.user_id))
        _desfazer_reserva(destino, alerta)  # não conta como enviado; tenta de novo na próxima
        return "erro no envio"
    _guardar_id_da_mensagem(destino, alerta, mensagem_id)
    return canal


# ---------- (1) resumo semanal ----------

def primeira_segunda_do_mes(segunda: date) -> bool:
    return segunda.day <= 7


def periodos_da_semana_passada(dia: date) -> financas.Periodos:
    """Segunda a domingo da semana passada, e a semana anterior a ela."""
    segunda = dia - timedelta(days=dia.weekday())
    inicio = segunda - timedelta(days=7)
    return inicio, segunda - timedelta(days=1), inicio - timedelta(days=7), segunda - timedelta(days=8)


def linhas_de_metas(metas: dict[str, Decimal], real_por_tipo: dict[str, Decimal], prefixo: str = "") -> list[str]:
    """Metas de gasto (tetos) em 80% ou mais, ou estouradas. Investimento e Reserva não entram."""
    linhas = []
    for tipo, meta in metas.items():
        if tipo in financas.TIPOS_MINIMOS or meta <= 0:
            continue
        real = real_por_tipo.get(tipo, Decimal("0"))
        pct = int(real / meta * 100)
        if pct >= 100:
            linhas.append(f"❌ {prefixo}{tipo}: passou da meta ({formatar_reais(real)} de {formatar_reais(meta)}).")
        elif pct >= 80:
            linhas.append(f"⚠️ {prefixo}{tipo}: {pct}% da meta ({formatar_reais(real)} de {formatar_reais(meta)}).")
    return linhas


def metas_do_mes(destino: Destinatario, dia: date, totais_do_mes: financas.Totais) -> list[str]:
    inicio = dia.replace(day=1)
    metas = _metas_em_reais(ler_metas(destino.account_id), ler_renda_conjunta(destino.account_id))
    linhas = linhas_de_metas(metas, totais_do_mes.por_tipo)
    if conta_em_casal(destino.account_id):
        individuais = _metas_em_reais(
            ler_metas(destino.account_id, destino.user_id), ler_renda(destino.account_id, destino.user_id)
        )
        real = financas.gastos_do_usuario_por_tipo(destino.account_id, destino.user_id, inicio, dia)
        linhas += linhas_de_metas(individuais, real, "Só seu — ")
    return linhas


def resumo_do_mes_passado(destino: Destinatario, dia: date) -> str | None:
    fim = dia.replace(day=1) - timedelta(days=1)
    totais = financas.totais_do_periodo(destino.account_id, destino.user_id, fim.replace(day=1), fim)
    if totais.vazio:
        return None
    return (f"Mês passado ({MESES[fim.month - 1]}): entradas {formatar_reais(totais.entradas)}, "
            f"saídas {formatar_reais(totais.saidas)}, saldo {formatar_reais(totais.saldo)}.")


def _dinheiro(valor: Decimal) -> str:
    return f"-{formatar_reais(-valor)}" if valor < 0 else formatar_reais(valor)


def alerta_resumo_semanal(destino: Destinatario, dia: date) -> tuple[Alerta | None, str]:
    segunda = dia - timedelta(days=dia.weekday())
    chave = f"{TIPO_RESUMO}:{segunda.isoformat()}"
    if ja_enviado(destino, chave):
        return None, "resumo da semana já enviado"
    periodos = periodos_da_semana_passada(dia)
    inicio, fim, inicio_ant, fim_ant = periodos
    atual = financas.totais_do_periodo(destino.account_id, destino.user_id, inicio, fim)
    if atual.vazio:
        return None, "sem movimento na semana passada"
    anterior = financas.totais_do_periodo(destino.account_id, destino.user_id, inicio_ant, fim_ant)
    fatos = [montar_resumo("Resumo da semana passada", periodos, atual, anterior)]
    extras = metas_do_mes(destino, dia, financas.totais_do_periodo(
        destino.account_id, destino.user_id, dia.replace(day=1), dia))
    if primeira_segunda_do_mes(segunda):
        mes_passado = resumo_do_mes_passado(destino, dia)
        if mes_passado:
            extras.append(mes_passado)
    fatos += extras
    periodo = f"{inicio:%d} a {fim:%d/%m}"
    destaque = " ".join(extras).replace("\n", " ") or "Nenhuma meta perto do limite."
    return Alerta(
        TIPO_RESUMO, chave, "\n".join(fatos), MODELO_RESUMO,
        [periodo, _dinheiro(atual.entradas), _dinheiro(atual.saidas), _dinheiro(atual.saldo), destaque],
        inicio, fim,
    ), "ok"


# ---------- (2) conta, assinatura ou parcela vencendo amanhã ----------

@dataclass
class Vencimento:
    nome: str
    valor: Decimal
    detalhe: str = ""  # ex.: "parcela 3/10"

    def linha(self) -> str:
        sufixo = f" ({self.detalhe})" if self.detalhe else ""
        return f"{self.nome}{sufixo}: {formatar_reais(self.valor)}"


def vencimentos_de_amanha(contas, parcelas: list[Parcelamento], dia: date) -> list[Vencimento]:
    """contas: (nome, valor, próximo vencimento). Parcelas: a que vence amanhã."""
    amanha = dia + timedelta(days=1)
    achados = [Vencimento(nome, valor) for nome, valor, proximo in contas if proximo == amanha]
    for p in parcelas:
        if p.proximo_vencimento(dia) == amanha:
            achados.append(Vencimento(p.nome, p.valor, f"parcela {p.total - p.restantes(dia) + 1}/{p.total}"))
    return achados


def _contas_e_parcelas(destino: Destinatario):
    """Só o que o usuário pode ver: as "meu" do parceiro ficam de fora."""
    with get_engine().connect() as connection:
        contas = connection.execute(
            text("SELECT payee, amount, next_due_date FROM recurring_transactions"
                 " WHERE account_id = :conta AND is_active AND next_due_date IS NOT NULL"
                 " AND (scope = 'conjunto' OR created_by_user_id = :usuario)"),
            {"conta": destino.account_id, "usuario": destino.user_id},
        ).all()
        parcelas = connection.execute(
            text("SELECT description, installment_amount, total_installments, first_due_date, due_day"
                 " FROM installments WHERE account_id = :conta"
                 " AND (scope = 'conjunto' OR created_by_user_id = :usuario)"),
            {"conta": destino.account_id, "usuario": destino.user_id},
        ).all()
    return ([(c.payee, c.amount, _como_data(c.next_due_date)) for c in contas],
            [Parcelamento(p.description, p.installment_amount, p.total_installments,
                          _como_data(p.first_due_date), p.due_day) for p in parcelas])


def _como_data(valor) -> date | None:
    if valor is None or isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def alerta_vencimento(destino: Destinatario, dia: date) -> tuple[Alerta | None, str]:
    amanha = dia + timedelta(days=1)
    chave = f"{TIPO_VENCIMENTO}:{amanha.isoformat()}"
    if ja_enviado(destino, chave):
        return None, "aviso de vencimento já enviado"
    contas, parcelas = _contas_e_parcelas(destino)
    achados = vencimentos_de_amanha(contas, parcelas, dia)
    if not achados:
        return None, "nada vence amanhã"
    total = sum((v.valor for v in achados), Decimal("0"))
    fatos = "\n".join([f"Vence amanhã ({amanha:%d/%m}):", *(f"• {v.linha()}" for v in achados),
                       f"Total: {formatar_reais(total)}."])
    lista = "; ".join(v.linha() for v in achados)
    return Alerta(TIPO_VENCIMENTO, chave, fatos, MODELO_VENCIMENTO,
                  [f"{amanha:%d/%m}", lista, formatar_reais(total)], amanha, amanha), "ok"


# ---------- (3) lembrete após 4 dias sem registros ----------

def ultima_atividade(destino: Destinatario) -> date:
    """Dia do último registro do usuário; sem nenhum, o dia em que ele se cadastrou."""
    with get_engine().connect() as connection:
        registro = connection.execute(
            text("SELECT MAX(created_at) FROM transactions WHERE created_by_user_id = :u"
                 " AND voided_at IS NULL"),
            {"u": destino.user_id},
        ).scalar()
        cadastro = connection.execute(
            text("SELECT created_at FROM users WHERE id = :u"), {"u": destino.user_id}
        ).scalar()
    momentos = [m for m in (_como_datetime(registro), _como_datetime(cadastro)) if m is not None]
    ultimo = max(m.astimezone(BRASIL) if m.tzinfo else m for m in momentos)
    return ultimo.date()


def alerta_lembrete(destino: Destinatario, dia: date) -> tuple[Alerta | None, str]:
    ultimo = ultima_atividade(destino)
    sem_registro = (dia - ultimo).days
    if sem_registro < DIAS_SEM_REGISTRO:
        return None, f"registrou há {sem_registro} dia(s)"
    chave = f"{TIPO_LEMBRETE}:{ultimo.isoformat()}"  # um lembrete por período parado
    if ja_enviado(destino, chave):
        return None, "lembrete já enviado"
    fatos = (f"Faz {sem_registro} dias que você não registra nada. "
             "Mande /gasto VALOR DESCRIÇÃO ou uma foto do comprovante.")
    return Alerta(TIPO_LEMBRETE, chave, fatos, MODELO_LEMBRETE, [str(sem_registro)], ultimo, dia), "ok"


# ---------- rota /cron ----------

def destinatarios() -> list[Destinatario]:
    """Usuários ativos, cada um com sua conta mais recente (como o resto do bot)."""
    with get_engine().connect() as connection:
        linhas = connection.execute(
            text("SELECT u.id AS user_id, u.phone_number, u.access_expires_at, m.account_id, m.joined_at"
                 " FROM users u JOIN members m ON m.user_id = u.id"
                 " WHERE u.access_status = 'ativo' ORDER BY m.joined_at"),
        ).all()
    agora = datetime.now(BRASIL)
    por_usuario: dict[str, Destinatario] = {}
    for l in linhas:
        validade = _como_datetime(l.access_expires_at)
        if validade is not None:
            if validade.tzinfo is None:
                validade = validade.replace(tzinfo=BRASIL)
            if validade <= agora:
                continue  # acesso vencido
        por_usuario[str(l.user_id)] = Destinatario(str(l.user_id), str(l.account_id), l.phone_number)
    return list(por_usuario.values())


def alertas_do_dia(destino: Destinatario, dia: date) -> list[tuple[str, Alerta | None, str]]:
    """Os candidatos em ordem de prioridade: (nome, alerta ou None, motivo de não haver)."""
    resultado = []
    for nome, criar in (("resumo semanal", alerta_resumo_semanal),
                        ("vencimento", alerta_vencimento),
                        ("lembrete", alerta_lembrete)):
        alerta, motivo = criar(destino, dia)
        resultado.append((nome, alerta, motivo))
    return resultado


def processar_usuario(destino: Destinatario, agora: datetime) -> None:
    """Envia no máximo 1 alerta (o mais prioritário que puder ser enviado agora)."""
    usuario = _curto(destino.user_id)
    if enviados_na_semana(destino.user_id, agora) >= LIMITE_SEMANAL:
        logger.info("Alerta pulado (usuário %s): limite de %d por semana", usuario, LIMITE_SEMANAL)
        return
    ultima = ultima_mensagem_do_usuario(destino.telefone)
    for nome, alerta, motivo in alertas_do_dia(destino, agora.astimezone(BRASIL).date()):
        if alerta is None:
            logger.info("Alerta %s pulado (usuário %s): %s", nome, usuario, motivo)
            continue
        resultado = enviar_alerta(destino, alerta, agora, ultima)
        if resultado in ("texto", "modelo"):
            logger.info("Alerta %s enviado (usuário %s) por %s", nome, usuario, resultado)
            return  # 1 por chamada: o resto fica para os próximos dias
        logger.info("Alerta %s pulado (usuário %s): %s", nome, usuario, resultado)


def executar_alertas(forcar: bool = False, agora: datetime | None = None) -> None:
    """Chamada pela rota /cron. Sem `forcar`, só age entre 10h e 10h59 (horário de Brasília)."""
    agora = agora or datetime.now(BRASIL)
    if not forcar and agora.astimezone(BRASIL).hour != HORA_DO_ENVIO:
        logger.info("Cron ignorado: são %s em Brasília (envio só às %dh)",
                    agora.astimezone(BRASIL).strftime("%H:%M"), HORA_DO_ENVIO)
        return
    for destino in destinatarios():
        try:
            processar_usuario(destino, agora)
        except Exception:
            logger.exception("Erro nos alertas do usuário %s", _curto(destino.user_id))


# ---------- gasto muito acima do normal (enviado logo depois da confirmação) ----------

# Alertas que o fluxo do gasto deixa prontos; o webhook envia depois da resposta de confirmação,
# para a ordem das mensagens ficar certa. None = ninguém está esperando (ex.: nos testes).
_fila: contextvars.ContextVar[list | None] = contextvars.ContextVar("fila_alertas", default=None)


def abrir_fila() -> None:
    _fila.set([])


def gasto_muito_acima(valor: Decimal, anteriores: list[Decimal]) -> Decimal | None:
    """Devolve a média anterior se o valor for 'muito acima do normal'; senão None."""
    if len(anteriores) < MIN_HISTORICO or valor < VALOR_MINIMO:
        return None
    media = sum(anteriores, Decimal("0")) / len(anteriores)
    return media if media > 0 and valor >= media * MULTIPLO else None


def _compras_anteriores(account_id, user_id, categoria_id, dia: date):
    """(id da compra que acabou de ser registrada, valores das compras anteriores da categoria).
    Só entra o que o usuário pode ver: do casal e as dele."""
    with get_engine().connect() as connection:
        ultima = connection.execute(
            text("SELECT id FROM transactions WHERE account_id = :conta AND created_by_user_id = :u"
                 " AND voided_at IS NULL AND transaction_type = 'expense'"
                 " ORDER BY created_at DESC LIMIT 1"),
            {"conta": account_id, "u": user_id},
        ).scalar()
        valores = connection.execute(
            text("SELECT amount FROM transactions WHERE account_id = :conta AND category_id = :cat"
                 " AND voided_at IS NULL AND transaction_type = 'expense' AND id <> :ultima"
                 " AND (scope = 'conjunto' OR created_by_user_id = :u)"
                 " AND transaction_date >= :desde"),
            {"conta": account_id, "cat": categoria_id, "ultima": ultima, "u": user_id,
             "desde": dia - timedelta(days=DIAS_DE_HISTORICO)},
        ).scalars().all()
    return ultima, [Decimal(str(v)) for v in valores]


def preparar_alerta_gasto(telefone: str, account_id, user_id, dados: dict, categoria) -> None:
    """Chamada quando o usuário confirma um gasto. Se estiver muito acima do normal, deixa um
    alerta na fila para o webhook enviar logo depois da confirmação."""
    fila = _fila.get()
    if fila is None:
        return
    try:
        valor = Decimal(dados["valor"])
        ultima, anteriores = _compras_anteriores(account_id, user_id, categoria.id, financas.hoje())
        media = gasto_muito_acima(valor, anteriores)
        if media is None:
            return
        fatos = (f"⚠️ {formatar_reais(valor)} em {categoria.nome} é bem acima do seu normal: "
                 f"a média por compra nessa categoria é {formatar_reais(media.quantize(Decimal('0.01')))}.")
        fila.append((Destinatario(str(user_id), str(account_id), telefone),
                     Alerta(TIPO_GASTO_ALTO, f"{TIPO_GASTO_ALTO}:{ultima}", fatos, "", [])))
    except Exception:
        logger.exception("Erro ao checar gasto acima do normal")


def enviar_alertas_de_gasto() -> None:
    """Envia (como texto comum: o usuário acabou de falar, então a janela está aberta) os alertas
    deixados na fila. Respeita o limite de 3 por semana."""
    from app import whatsapp

    fila, agora = _fila.get() or [], datetime.now(BRASIL)
    _fila.set(None)
    for destino, alerta in fila:
        usuario = _curto(destino.user_id)
        if enviados_na_semana(destino.user_id, agora) >= LIMITE_SEMANAL:
            logger.info("Alerta gasto_alto pulado (usuário %s): limite de %d por semana", usuario, LIMITE_SEMANAL)
            continue
        if not _reservar(destino, alerta):
            logger.info("Alerta gasto_alto pulado (usuário %s): já enviado", usuario)
            continue
        try:
            mensagem_id = whatsapp.send_text(destino.telefone, texto_do_alerta(alerta.fatos))
        except Exception:
            logger.exception("Falha ao enviar alerta gasto_alto ao usuário %s", usuario)
            _desfazer_reserva(destino, alerta)
            continue
        _guardar_id_da_mensagem(destino, alerta, mensagem_id)
        logger.info("Alerta gasto_alto enviado (usuário %s) por texto", usuario)
