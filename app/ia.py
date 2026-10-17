import base64
import json
import logging
import os
import re

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODELO_PADRAO = "claude-haiku-5-5"


def chamar_ia(sistema: str, mensagem: str | list, max_tokens: int = 150) -> str | None:
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


def pedir_json(sistema: str, mensagem: str | list, max_tokens: int = 150) -> dict | None:
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


SISTEMA_COMPROVANTE = (
    "Você lê comprovantes de pagamento ou Pix brasileiros (foto ou PDF). "
    'Responda só com JSON: {"valor": "45,90", "data": "16/10/2026", "favorecido": "Padaria Pão Quente"}. '
    "O favorecido é quem recebeu o pagamento (nome curto). Copie os dados como estão no "
    'comprovante, sem calcular nada. Use null no que não conseguir ler. '
    "Se a imagem não for um comprovante de pagamento, responda {\"valor\": null}."
)

TIPOS_DE_IMAGEM = ("image/jpeg", "image/png", "image/webp", "image/gif")
TIPO_PDF = "application/pdf"


def _bloco_arquivo(conteudo: bytes, tipo: str) -> dict:
    return {
        "type": "document" if tipo == TIPO_PDF else "image",
        "source": {
            "type": "base64",
            "media_type": tipo,
            "data": base64.b64encode(conteudo).decode(),
        },
    }


def ler_comprovante(conteudo: bytes, tipo: str) -> dict | None:
    """Foto ou PDF de comprovante -> {"valor", "data", "favorecido"} (textos, sem cálculo).

    O arquivo só é usado nesta chamada; nada dele é guardado.
    """
    mensagem = [
        _bloco_arquivo(conteudo, tipo),
        {"type": "text", "text": "Extraia os dados deste comprovante."},
    ]
    dados = pedir_json(SISTEMA_COMPROVANTE, mensagem, max_tokens=120)
    if not dados or not dados.get("valor"):
        return None
    return {
        "valor": str(dados["valor"]),
        "data": str(dados["data"]) if dados.get("data") else None,
        "favorecido": str(dados["favorecido"]) if dados.get("favorecido") else None,
    }


SISTEMA_HOLERITE = (
    "Você lê holerites (contracheques) brasileiros em foto ou PDF. "
    'Responda só com JSON: {"valor": "4.500,00", "data": "05/10/2026"}. '
    "O valor é o LÍQUIDO a receber (não o bruto). A data é a do pagamento; se não houver, "
    "use o último dia do mês de referência. Copie os dados como estão no documento, sem "
    "calcular nada. Use null no que não conseguir ler. "
    'Se não for um holerite, responda {"valor": null}.'
)


def ler_holerite(conteudo: bytes, tipo: str) -> dict | None:
    """Foto ou PDF de holerite -> {"valor": líquido, "data"} (textos, sem cálculo).

    O arquivo só é usado nesta chamada; nada dele é guardado.
    """
    mensagem = [
        _bloco_arquivo(conteudo, tipo),
        {"type": "text", "text": "Extraia o valor líquido e a data."},
    ]
    dados = pedir_json(SISTEMA_HOLERITE, mensagem, max_tokens=80)
    if not dados or not dados.get("valor"):
        return None
    return {
        "valor": str(dados["valor"]),
        "data": str(dados["data"]) if dados.get("data") else None,
    }


def entender_gasto(frase: str) -> dict | None:
    """Frase livre -> {"valor": "45,90", "descricao": "mercado"} (texto, sem cálculo)."""
    dados = pedir_json(SISTEMA_GASTO, frase, max_tokens=60)
    if not dados or not dados.get("valor"):
        return None
    return {"valor": str(dados["valor"]), "descricao": str(dados.get("descricao") or "")}


SISTEMA_COMANDO = (
    "Você escolhe qual comando de um bot de finanças no WhatsApp o usuário quer, a partir de "
    "uma frase em português do Brasil. Comandos: resumo (resumo do mês; argumento \"semana\" "
    "para a semana), gasto (argumento: valor e descrição), entrada (argumento: valor e "
    "descrição), metas, categorias, fixos, previsao (previsão do fim do mês), diagnostico, "
    "objetivos, parcelas, desfazer, privacidade, inicio, ajuda. "
    'Responda só com JSON: {"comando": "resumo", "argumentos": "semana"}. '
    "Só escolha um comando se a intenção for clara. Cumprimentos, agradecimentos e conversa "
    'em geral não são comandos. Se a frase não pedir nenhum desses, responda {"comando": null}. '
    "Não calcule nada."
)


def identificar_comando(frase: str) -> tuple[str, str] | None:
    """Frase livre -> (nome do comando, argumentos). Quem chama confere se o comando é permitido."""
    dados = pedir_json(SISTEMA_COMANDO, frase[:300], max_tokens=40)
    if not dados or not isinstance(dados.get("comando"), str):
        return None
    nome = dados["comando"].strip().lstrip("/").lower()
    argumentos = dados.get("argumentos")
    return (nome, argumentos.strip() if isinstance(argumentos, str) else "") if nome else None


SISTEMA_DIAGNOSTICO = (
    "Você é a Dona Fatura, assistente financeira no WhatsApp: direta e objetiva, firme ao avisar "
    "de gasto fora do plano, sem esconder o problema, com um toque de simpatia e sem sermão. "
    "Recebe um diagnóstico com números JÁ CALCULADOS. Reescreva em português do Brasil, mantendo "
    "a mesma estrutura (uma linha por tipo, com os mesmos sinais ✅ ⚠️ ❌, depois os ajustes e o "
    "saldo previsto), todos os fatos e o tamanho curto; só ajuste o tom. Use SÓ os números e valores recebidos, "
    "exatamente como estão; não calcule, não some, não arredonde, não invente nada."
)


def escrever_diagnostico(fatos: str) -> str | None:
    """Diagnóstico com números prontos -> texto final no tom da Dona Fatura (a IA não calcula)."""
    return chamar_ia(SISTEMA_DIAGNOSTICO, fatos, max_tokens=400)


def sugerir_categoria(descricao: str, categorias: list[str]) -> str | None:
    """Devolve o nome da categoria escolhida pela IA (quem chama confere se existe)."""
    lista = ", ".join(categorias)
    return chamar_ia(
        SISTEMA_CATEGORIA, f"Gasto: {descricao}\nCategorias: {lista}", max_tokens=20
    )
