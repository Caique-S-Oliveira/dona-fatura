import re
import unicodedata
from decimal import Decimal, InvalidOperation


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento: "/Previsão" -> "/previsao"."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def eh_sim(texto: str) -> bool:
    return normalizar(texto).strip(" .!") in ("sim", "s", "ok", "isso", "confirmo", "pode", "certo")


def eh_nao(texto: str) -> bool:
    return normalizar(texto).strip(" .!") in ("nao", "n", "cancelar", "cancela")


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
