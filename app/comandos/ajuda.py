from app.comandos.acesso import cadastro_completo, eh_admin

TEXTO_AJUDA = """*Dona Fatura - comandos*

*Registrar*
/gasto 45,90 mercado
/entrada 3000 salário
/desfazer - desfaz o último registro
Também vale escrever: "gastei 45 no mercado" ou mandar a foto/PDF do comprovante.

*Acompanhar*
/resumo - mês (/resumo semana)
/previsao - como o mês termina
/diagnostico - real x meta e o que ajustar
/grafico previsao - gráfico da previsão
/fixos - contas fixas pagas e a vencer

*Planejar*
/inicio - configurar renda e metas
/metas - ver e alterar metas
/categorias - ver e criar categorias
/objetivos - poupança (nome, valor, prazo)
/parcelas - compras parceladas
/pagar - pagar uma parcela (ex.: /pagar carro)

*A dois*
/casal - gera um código para o parceiro
/entrar CÓDIGO - entrar na conta do casal
/sair_casal - separar as contas

*Dados*
/privacidade - o que é guardado
/apagar_meus_dados - apaga tudo"""


TEXTO_INICIAR = """*Dona Fatura*
Eu registro seus ganhos e gastos aqui no WhatsApp, comparo com suas metas e aviso o que corrigir.

Mande /inicio para configurar seu nome, renda e metas. Leva uns 2 minutos."""

TEXTO_ADMIN = """*Administração*
/pendentes - pedidos de acesso (com botões)
/liberar NÚMERO
/negar NÚMERO
/usuarios - números e status"""


def comando_ajuda(argumentos: str) -> str:
    return TEXTO_AJUDA


def comando_ajuda_usuario(telefone: str, argumentos: str) -> str:
    """Ajuda conforme quem pergunta: sem /inicio concluído só explica como começar."""
    texto = TEXTO_AJUDA if cadastro_completo(telefone) else TEXTO_INICIAR
    if eh_admin(telefone):
        texto += "\n\n" + TEXTO_ADMIN
    return texto
