from dataclasses import dataclass


@dataclass
class Resposta:
    """Resposta interativa do WhatsApp: botões (no máximo 3) ou lista (no máximo 10 linhas).

    botoes: títulos de até 20 letras.
    lista: linhas (id, título de até 24 letras, descrição de até 72); botao_lista abre a lista.
    """

    texto: str
    botoes: tuple[str, ...] = ()
    lista: tuple[tuple[str, str, str], ...] = ()
    botao_lista: str = "Escolher"
    titulo_lista: str = "Categorias"  # título da seção da lista (até 24 letras)
    imagem: bytes | None = None  # PNG; o texto vira a legenda
    documento: tuple[str, bytes] | None = None  # (nome do arquivo, conteúdo .xlsx); o texto vira a legenda
