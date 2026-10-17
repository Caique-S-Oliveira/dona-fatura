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

*A dois*
/casal - gera um código para o parceiro
/entrar CÓDIGO - entrar na conta do casal
/sair_casal - separar as contas

*Dados*
/privacidade - o que é guardado
/apagar_meus_dados - apaga tudo"""


def comando_ajuda(argumentos: str) -> str:
    return TEXTO_AJUDA
