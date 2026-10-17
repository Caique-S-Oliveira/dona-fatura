from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from app import ia
from app.comandos.cadastro import conta_do_usuario
from app.comandos.formato import ler_numero
from app.comandos.gasto import comecar_gasto
from app.comandos.resposta import Resposta

TIPOS_ACEITOS = (*ia.TIPOS_DE_IMAGEM, ia.TIPO_PDF)
MSG_TIPO = "Só leio foto (JPG ou PNG) ou PDF. Ou mande: /gasto 45,90 mercado"
MSG_NAO_LEU = "Não consegui ler esse comprovante. Mande um texto, ex.: /gasto 45,90 mercado"
SEM_FAVORECIDO = "Comprovante"
BRASIL = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem horário de verão desde 2019)


def ler_data(texto: str | None) -> str | None:
    """"16/10/2026" ou "2026-10-16" -> "2026-10-16". Inválida ou futura -> None (vale hoje)."""
    if not texto:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            data = datetime.strptime(texto.strip(), formato).date()
        except ValueError:
            continue
        hoje: date = datetime.now(BRASIL).date()
        return data.isoformat() if data <= hoje else None
    return None


def montar_dados(extraido: dict) -> dict | None:
    """Resposta da IA -> dados do gasto (o mesmo formato do /gasto, com data e favorecido)."""
    valor = ler_numero(extraido["valor"])
    if valor is None or valor <= 0:
        return None
    favorecido = (extraido.get("favorecido") or "").strip()[:60]
    dados = {
        "valor": str(valor),
        "descricao": favorecido or SEM_FAVORECIDO,
        "escopo": "conjunto",
        "fonte": "receipt",
    }
    if favorecido:
        dados["favorecido"] = favorecido
    else:
        dados["aprender"] = False  # sem favorecido não há o que aprender
    data = ler_data(extraido.get("data"))
    if data:
        dados["data"] = data
    return dados


def receber_comprovante(
    telefone: str, tipo: str, baixar: Callable[[], bytes | None]
) -> str | Resposta:
    """Foto/PDF -> IA extrai valor, data e favorecido -> sugere categoria -> [Sim] [Corrigir].

    O arquivo só existe nesta função: depois de lido pela IA ele é descartado
    e só valor, data, favorecido e categoria seguem (e só são salvos após o "Sim").
    """
    if tipo not in TIPOS_ACEITOS:
        return MSG_TIPO
    conteudo = baixar()
    if conteudo is None:
        return MSG_NAO_LEU
    try:
        extraido = ia.ler_comprovante(conteudo, tipo)
    finally:
        del conteudo  # descarta o arquivo
    dados = montar_dados(extraido) if extraido else None
    if dados is None:
        return MSG_NAO_LEU

    _, account_id = conta_do_usuario(telefone)
    return comecar_gasto(telefone, account_id, dados, escopo_explicito=False)
