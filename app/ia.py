import json
import logging
import os
import re

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODELO_PADRAO = "claude-haiku-5-5"


def chamar_ia(sistema: str, mensagem: str, max_tokens: int = 150) -> str | None:
    """Manda uma mensagem curta para o Claude e devolve o texto da resposta.

    Devolve None se a IA não estiver configurada ou se der erro (o bot segue sem ela).
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY não definida; IA desligada.")
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning("Biblioteca anthropic não instalada; IA desligada.")
        return None

    modelo = os.getenv("ANTHROPIC_MODEL") or MODELO_PADRAO
    extras = {"output_config": {"effort": "low"}}
    if "haiku" in modelo:
        extras["thinking"] = {"type": "disabled"}  # tarefa simples: sem raciocínio, mais barato
    try:
        cliente = anthropic.Anthropic(timeout=20.0, max_retries=1)
        resposta = cliente.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            system=sistema,
            messages=[{"role": "user", "content": mensagem}],
            **extras,
        )
    except anthropic.APIStatusError as erro:
        logger.error("Erro da API do Claude (%s): %s", erro.status_code, erro.message)
        return None
    except anthropic.APIConnectionError:
        logger.error("Sem conexão com a API do Claude.")
        return None
    if resposta.stop_reason == "refusal":
        return None
    texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text")
    return texto.strip() or None


def pedir_json(sistema: str, mensagem: str, max_tokens: int = 150) -> dict | None:
    """Como chamar_ia, mas lê a resposta como JSON. Devolve None se não vier um objeto."""
    texto = chamar_ia(sistema, mensagem, max_tokens)
    if texto is None:
        return None
    achado = re.search(r"\{.*\}", texto, re.DOTALL)
    if achado is None:
        return None
    try:
        dados = json.loads(achado.group())
    except ValueError:
        return None
    return dados if isinstance(dados, dict) else None


# ---------- usos específicos ----------

SISTEMA_GASTO = (
    "Você lê mensagens de WhatsApp em português do Brasil e extrai um gasto. "
    'Responda só com JSON: {"valor": "45,90", "descricao": "mercado"}. '
    "A descrição é curta (1 a 3 palavras: o que foi comprado ou onde). "
    'Se a mensagem não informar um gasto com valor, responda {"valor": null}.'
)

SISTEMA_CATEGORIA = (
    "Você classifica gastos pessoais. Recebe a descrição de um gasto e uma lista de "
    "categorias. Responda só com o nome exato de uma categoria da lista, nada mais."
)


def entender_gasto(frase: str) -> dict | None:
    """Frase livre -> {"valor": "45,90", "descricao": "mercado"} (texto, sem cálculo)."""
    dados = pedir_json(SISTEMA_GASTO, frase, max_tokens=60)
    if not dados or not dados.get("valor"):
        return None
    return {"valor": str(dados["valor"]), "descricao": str(dados.get("descricao") or "")}


def sugerir_categoria(descricao: str, categorias: list[str]) -> str | None:
    """Devolve o nome da categoria escolhida pela IA (quem chama confere se existe)."""
    lista = ", ".join(categorias)
    return chamar_ia(
        SISTEMA_CATEGORIA, f"Gasto: {descricao}\nCategorias: {lista}", max_tokens=20
    )
