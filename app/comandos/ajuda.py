TEXTO_AJUDA = """Comandos da Dona Fatura:
/inicio - configurar renda e metas
/gasto VALOR DESCRIÇÃO - registrar um gasto
/entrada VALOR DESCRIÇÃO - registrar uma entrada
/resumo - resumo do mês (/resumo semana)
/previsao - previsão do fim do mês
/diagnostico - real x meta e o que ajustar
/metas /categorias /fixos /objetivos /parcelas
/grafico previsao - gráfico da previsão
/desfazer - desfaz o último registro
/casal /entrar CÓDIGO /grupo - usar a dois
/sair_casal - separar as contas do casal
/privacidade /apagar_meus_dados /ajuda"""


def comando_ajuda(argumentos: str) -> str:
    return TEXTO_AJUDA
