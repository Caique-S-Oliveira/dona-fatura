import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento: "/Previsão" -> "/previsao"."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def eh_sim(texto: str) -> bool:
    return normalizar(texto).strip(" .!") in ("sim", "s", "ok", "isso", "confirmo", "pode", "certo")


def eh_nao(texto: str) -> bool:
    return normalizar(texto).strip(" .!") in ("nao", "n", "cancelar", "cancela")


_RELATIVAS = {"hoje": 0, "ontem": 1, "anteontem": 2}
_PALAVRA_DATA = re.compile(r"(?<!\w)(hoje|ontem|anteontem)(?!\w)", re.IGNORECASE)
_DIA_N = re.compile(r"(?<!\w)dia\s+(\d{1,2})(?![\d/])", re.IGNORECASE)
_DD_MM = re.compile(r"(?<![\d/.,])(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?(?![\d/])")
MSG_DATA = "Não entendi a data. Use: dia 3, ontem ou 03/10."


def separar_data(texto: str, hoje: date) -> tuple[str, date | None]:
    """Tira "dia 3", "ontem" ou "dd/mm" do texto: "45 mercado dia 3" -> ("45 mercado", 03 do mês).

    Sem data devolve (texto, None). Data que não existe (ex.: 31/02) levanta ValueError.
    """
    for padrao in (_DD_MM, _DIA_N, _PALAVRA_DATA):
        achado = padrao.search(texto)
        if achado:
            break
    else:
        return texto.strip(), None
    if padrao is _PALAVRA_DATA:
        data = hoje - timedelta(days=_RELATIVAS[achado[1].lower()])
    elif padrao is _DIA_N:
        data = date(hoje.year, hoje.month, int(achado[1]))
    else:
        ano = int(achado[3]) if achado[3] else hoje.year
        data = date(ano + 2000 if ano < 100 else ano, int(achado[2]), int(achado[1]))
    resto = " ".join((texto[: achado.start()] + " " + texto[achado.end():]).split())
    return resto, data


def ler_numero(texto: str) -> Decimal | None:
    """Lê "4500", "4.500,00", "R$ 45,90" ou "30%" -> Decimal. Devolve None se não for número."""
    limpo = texto.strip().lower().replace("r$", "").replace(" ", "").rstrip("%")
    if not re.fullmatch(r"[\d.,]*\d[\d.,]*", limpo):
        return None
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", limpo):
        limpo = limpo.replace(".", "")  # "4.500" é quatro mil e quinhentos
    try:
        return Decimal(limpo).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def formatar_reais(valor: Decimal) -> str:
    """Decimal("1234.5") -> "R$ 1.234,50"."""
    texto = f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def formatar_pct(valor: Decimal) -> str:
    """Decimal("30.00") -> "30%"; Decimal("12.50") -> "12,5%"."""
    texto = f"{valor:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{texto}%"
