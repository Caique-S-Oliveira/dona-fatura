from decimal import Decimal

from sqlalchemy import text

from app.comandos.cadastro import conta_do_usuario
from app.comandos.casal import conta_em_casal
from app.comandos.estado import limpar_estado, salvar_estado
from app.comandos.formato import formatar_pct, ler_numero, normalizar
from app.comandos.metas import (
    PADRAO_50_30_20,
    TIPOS,
    aviso_acima_da_renda,
    linhas_metas,
    soma_pct,
    substituir_metas,
)
from app.db import get_engine

ESTADO = "inicio"

DICAS = {
    "Fixo": "moradia, contas, parcelas",
    "Variável": "mercado, transporte, lazer",
    "Assinatura": "streaming, apps",
    "Investimento": "o que vai investir",
    "Reserva de emergência": "o que vai guardar",
}

PERGUNTA_FORMATO = (
    "Como quer definir suas metas?\n"
    "1 - R$ por tipo (recomendado)\n"
    "2 - % da renda\n"
    "3 - usar 50/30/20 (pronto, em %)"
)

MSG_PRIVACIDADE = (
    "Privacidade: guardo só seu nome, renda, metas e os registros que você confirmar "
    "(valor, data, favorecido e categoria). Fotos e PDFs são descartados depois da leitura. "
    "Quem administra o banco de dados consegue ver esses dados. "
    "Para apagar tudo: /apagar_meus_dados."
)


def comando_inicio(telefone: str, argumentos: str) -> str:
    salvar_estado(telefone, ESTADO, {"passo": "nome"})
    return "Vamos configurar sua conta.\nPrimeiro: como você quer ser chamado(a)?"


def _metas(dados: dict) -> dict[str, tuple[str, Decimal]]:
    """Metas guardadas no estado (texto no JSON) -> {tipo: (formato, Decimal)}."""
    return {
        tipo: (dados["formato"], Decimal(valor))
        for tipo, valor in dados.get("metas", {}).items()
    }


def _pergunta_meta(dados: dict) -> str:
    tipo = TIPOS[dados["indice"]]
    if dados["formato"] == "amount":
        return (
            f"Meta de {tipo} ({DICAS[tipo]}) por mês, em R$?\n"
            "Ex.: 1500. Mande 0 para pular."
        )
    livre = Decimal("100") - soma_pct(_metas(dados))
    return (
        f"Quantos % da renda para {tipo} ({DICAS[tipo]})?\n"
        f"Ex.: 30. Ainda dá para usar até {formatar_pct(livre)}. Mande 0 para pular."
    )


def proximo_passo(dados: dict, texto: str) -> tuple[str, dict]:
    """Recebe a resposta do usuário e devolve (próxima mensagem, dados atualizados).

    Quando termina, dados["passo"] vira "fim" (quem chama grava tudo no banco).
    """
    dados = dict(dados)
    resposta = texto.strip()
    passo = dados.get("passo")

    if passo == "nome":
        if not resposta or len(resposta) > 40:
            return "Mande só o nome, por favor (até 40 letras).", dados
        dados.update(passo="renda", nome=resposta)
        return (
            f"Prazer, {resposta}! Qual sua renda mensal esperada (líquida)?\n"
            "Ex.: 4500 ou 4.500,00"
        ), dados

    if passo == "renda":
        renda = ler_numero(resposta)
        if renda is None or renda <= 0:
            return "Não entendi o valor. Mande só o número, ex.: 4500 ou 4.500,00", dados
        dados.update(passo="formato", renda=str(renda))
        return PERGUNTA_FORMATO, dados

    if passo == "formato":
        escolha = normalizar(resposta).replace(" ", "")
        if escolha in ("1", "r$", "rs", "reais", "valor"):
            dados.update(passo="meta", formato="amount", indice=0, metas={})
        elif escolha in ("2", "%", "porcentagem", "percentual"):
            dados.update(passo="meta", formato="percentage", indice=0, metas={})
        elif escolha in ("3", "50/30/20", "503020", "usar50/30/20"):
            metas = {tipo: str(pct) for tipo, pct in PADRAO_50_30_20.items()}
            dados.update(passo="fim", formato="percentage", metas=metas)
            return "", dados
        else:
            return "Responda 1, 2 ou 3.\n" + PERGUNTA_FORMATO, dados
        return _pergunta_meta(dados), dados

    if passo == "meta":
        valor = ler_numero(resposta)
        if valor is None or valor < 0:
            return "Não entendi o valor. " + _pergunta_meta(dados), dados
        tipo = TIPOS[dados["indice"]]
        if dados["formato"] == "percentage":
            livre = Decimal("100") - soma_pct(_metas(dados))
            if valor > livre:
                return (
                    f"Assim a soma passa de 100%. Para {tipo} dá para usar até "
                    f"{formatar_pct(livre)}."
                ), dados
        if valor > 0:
            dados["metas"] = {**dados["metas"], tipo: str(valor)}
        dados["indice"] += 1
        if dados["indice"] < len(TIPOS):
            return _pergunta_meta(dados), dados
        dados["passo"] = "fim"
        return "", dados

    # Estado desconhecido: recomeça.
    return "Vamos recomeçar. Como você quer ser chamado(a)?", {"passo": "nome"}


def mensagem_final(dados: dict, casal: bool = False) -> str:
    metas = _metas(dados)
    renda = Decimal(dados["renda"])
    titulo = "Suas metas (só suas; as do casal ficam em /metas):" if casal else "Suas metas:"
    partes = [f"Pronto, {dados['nome']}! {titulo}", linhas_metas(metas, renda)]
    aviso = aviso_acima_da_renda(metas, renda)
    if aviso:
        partes.append(aviso)
    partes.append("Veja ou altere quando quiser em /metas.")
    return "\n".join(partes) + "\n\n" + MSG_PRIVACIDADE


def gravar_inicio(telefone: str, dados: dict) -> bool:
    """Grava nome, renda e metas de uma vez só (nada é salvo antes do fim).

    No casal as metas daqui são individuais, para não apagar as metas do casal.
    Devolve True se a conta é de casal.
    """
    user_id, account_id = conta_do_usuario(telefone)
    casal = conta_em_casal(account_id)
    with get_engine().begin() as connection:
        connection.execute(
            text("UPDATE users SET display_name = :nome WHERE id = :usuario"),
            {"nome": dados["nome"], "usuario": user_id},
        )
        connection.execute(
            text(
                "UPDATE members SET expected_income = :renda"
                " WHERE account_id = :conta AND user_id = :usuario"
            ),
            {"renda": Decimal(dados["renda"]), "conta": account_id, "usuario": user_id},
        )
        substituir_metas(connection, account_id, _metas(dados), user_id if casal else None)
    return casal


def continuar_inicio(telefone: str, dados: dict, texto: str) -> str:
    resposta, dados = proximo_passo(dados, texto)
    if dados["passo"] != "fim":
        salvar_estado(telefone, ESTADO, dados)
        return resposta
    casal = gravar_inicio(telefone, dados)
    limpar_estado(telefone)
    return mensagem_final(dados, casal)
