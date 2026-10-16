import os
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app import ia
from app.comandos import processar_mensagem
from app.comandos.categorias import (
    PADRAO,
    Categoria,
    achar_categoria,
    categoria_por_palavra,
    continuar_categorias,
    continuar_nova,
    dividir,
    interpretar,
    ler_pedido_criar,
    lista_categorias,
)
from app.comandos.desfazer import continuar_desfazer, descrever
from app.comandos.gasto import continuar_gasto, ler_comando, ler_frase, parece_gasto
from app.comandos.resposta import Resposta
from app.whatsapp import message_text, send_list

USUARIO = "5511988887777"
CATEGORIAS = [Categoria(str(i), nome, tipo) for i, (nome, tipo) in enumerate(PADRAO.items(), 1)]
CONTA = ("usuario-1", "conta-1")


def lista_falsa(conta, usuario, texto, pagina=None):
    """Troca abrir_lista (que consulta o banco) por uma lista montada com as categorias de teste."""
    return lista_categorias(texto, CATEGORIAS, [], pagina)


def categoria(nome):
    return next(c for c in CATEGORIAS if c.nome == nome)


class TestLeituraDoGasto(unittest.TestCase):
    def test_comando(self):
        self.assertEqual(ler_comando("45,90 mercado"), (Decimal("45.90"), "mercado", "conjunto"))
        self.assertEqual(ler_comando("R$ 30 padaria meu"), (Decimal("30.00"), "padaria", "meu"))
        self.assertIsNone(ler_comando("45,90"))
        self.assertIsNone(ler_comando("mercado 45"))
        self.assertIsNone(ler_comando("0 mercado"))

    def test_frase(self):
        self.assertEqual(ler_frase("gastei 45 no mercado"), (Decimal("45.00"), "mercado", "conjunto"))
        self.assertEqual(ler_frase("Paguei R$ 30,50 de uber"), (Decimal("30.50"), "uber", "conjunto"))
        self.assertEqual(ler_frase("comprei 12 reais de pão"), (Decimal("12.00"), "pão", "conjunto"))
        self.assertEqual(ler_frase("gastei 1.200 na viagem meu"), (Decimal("1200.00"), "viagem", "meu"))
        self.assertIsNone(ler_frase("gastei muito no mercado"))
        self.assertIsNone(ler_frase("oi tudo bem"))

    def test_parece_gasto(self):
        self.assertTrue(parece_gasto("ontem gastei uns cinquenta no bar"))
        self.assertFalse(parece_gasto("bom dia"))


class TestCategorias(unittest.TestCase):
    def test_padrao_tem_pets_e_parcelas(self):
        self.assertIn("Pets", PADRAO)
        self.assertIn("Parcelas/dívidas", PADRAO)

    def test_achar_pelo_nome(self):
        self.assertEqual(achar_categoria(CATEGORIAS, "mercado").nome, "Mercado")
        self.assertEqual(achar_categoria(CATEGORIAS, "saude").nome, "Saúde")
        self.assertEqual(achar_categoria(CATEGORIAS, "parcela do carro").nome, "Parcelas/dívidas")
        self.assertIsNone(achar_categoria(CATEGORIAS, "uber"))

    def test_palavras_comuns(self):
        self.assertEqual(categoria_por_palavra(CATEGORIAS, "Uber").nome, "Transporte")
        self.assertEqual(categoria_por_palavra(CATEGORIAS, "ração").nome, "Pets")
        self.assertIsNone(categoria_por_palavra(CATEGORIAS, "presente"))

    def test_interpretar_resposta_da_lista(self):
        self.assertEqual(interpretar(CATEGORIAS, "cat:7"), ("categoria", categoria("Pets")))
        self.assertEqual(interpretar(CATEGORIAS, "lazer"), ("categoria", categoria("Lazer")))
        self.assertEqual(interpretar(CATEGORIAS, "acao:outras"), ("acao", "outras"))
        self.assertEqual(interpretar(CATEGORIAS, "Outras…"), ("acao", "outras"))
        self.assertEqual(interpretar(CATEGORIAS, "➕ Nova categoria"), ("acao", "nova"))
        self.assertEqual(interpretar(CATEGORIAS, "Mais…"), ("acao", "mais"))
        self.assertIsNone(interpretar(CATEGORIAS, "cat:999"))
        self.assertIsNone(interpretar(CATEGORIAS, "acao:xyz"))
        self.assertIsNone(interpretar(CATEGORIAS, "xyz"))


class TestListaDeCategorias(unittest.TestCase):
    def titulos(self, resposta):
        return [titulo for _, titulo, _ in resposta.lista]

    def test_principais_usam_as_mais_usadas_primeiro(self):
        usadas = ["7", "3"]  # Pets e Transporte
        principais, resto = dividir(CATEGORIAS, usadas)
        self.assertEqual([c.nome for c in principais[:2]], ["Pets", "Transporte"])
        self.assertEqual(len(principais), 8)
        self.assertEqual(len(principais) + len(resto), len(CATEGORIAS))

    def test_primeira_tela_tem_no_maximo_10_linhas(self):
        resposta = lista_categorias("Qual?", CATEGORIAS, ["7"])
        self.assertEqual(len(resposta.lista), 10)  # 8 + Outras… + Nova
        self.assertEqual(self.titulos(resposta)[-2:], ["Outras…", "➕ Nova categoria"])
        self.assertEqual(self.titulos(resposta)[0], "Pets")

    def test_sem_resto_nao_mostra_outras(self):
        resposta = lista_categorias("Qual?", CATEGORIAS[:5], [])
        self.assertEqual(self.titulos(resposta)[-1], "➕ Nova categoria")
        self.assertNotIn("Outras…", self.titulos(resposta))

    def test_outras_mostra_o_resto_e_nova(self):
        resposta = lista_categorias("Qual?", CATEGORIAS, [], pagina=0)
        self.assertEqual(len(resposta.lista), len(CATEGORIAS) - 8 + 1)
        self.assertEqual(self.titulos(resposta)[-1], "➕ Nova categoria")

    def test_outras_pagina_com_mais_e_nunca_passa_de_10(self):
        muitas = CATEGORIAS + [Categoria(f"x{i}", f"Extra {i}", "Variável") for i in range(20)]
        primeira = lista_categorias("Qual?", muitas, [], pagina=0)
        self.assertEqual(len(primeira.lista), 10)  # 8 + Mais… + Nova
        self.assertIn("Mais…", self.titulos(primeira))
        ultima = lista_categorias("Qual?", muitas, [], pagina=2)  # 23 no resto: páginas 0, 1 e 2
        self.assertNotIn("Mais…", self.titulos(ultima))
        self.assertLessEqual(len(ultima.lista), 10)

    def test_pedido_criar(self):
        self.assertEqual(ler_pedido_criar("academia variavel"), ("Academia", "Variável"))
        self.assertEqual(ler_pedido_criar("Streaming assinatura"), ("Streaming", "Assinatura"))
        self.assertEqual(ler_pedido_criar("Presentes"), ("Presentes", "Variável"))
        self.assertEqual(
            ler_pedido_criar("Cofrinho reserva de emergencia"), ("Cofrinho", "Reserva de emergência")
        )
        self.assertIsNone(ler_pedido_criar(""))


@patch("app.comandos.ler_estado", return_value=None)
@patch("app.comandos.garantir_usuario", return_value=False)
@patch("app.comandos.status_acesso", return_value="ativo")
@patch("app.comandos.limpar_estado")
@patch("app.comandos.gasto.salvar_estado")
@patch("app.comandos.gasto.abrir_lista", side_effect=lista_falsa)
@patch("app.comandos.gasto.listar_categorias", return_value=CATEGORIAS)
@patch("app.comandos.gasto.conta_do_usuario", return_value=CONTA)
class TestFluxoGasto(unittest.TestCase):
    @patch("app.comandos.gasto.ia.sugerir_categoria")
    @patch("app.comandos.gasto.regra_aprendida", return_value=None)
    def test_comando_sugere_e_pede_confirmacao(self, _regra, ia_categoria, _conta, _lista, _abrir, salvar, *_):
        resposta = processar_mensagem(USUARIO, "/gasto 45,90 mercado")
        self.assertIsInstance(resposta, Resposta)
        self.assertEqual(resposta.botoes, ("Sim", "Corrigir"))
        self.assertIn("R$ 45,90", resposta.texto)
        self.assertIn("Categoria: Mercado", resposta.texto)
        self.assertEqual(salvar.call_args.args[2]["passo"], "confirmar")
        ia_categoria.assert_not_called()  # regra resolveu, sem IA

    @patch("app.comandos.gasto.regra_aprendida", return_value="7")
    def test_regra_aprendida_vem_primeiro(self, _regra, *_):
        resposta = processar_mensagem(USUARIO, "gastei 80 no mercado")
        self.assertIn("Categoria: Pets", resposta.texto)

    @patch("app.comandos.gasto.ia.sugerir_categoria", return_value="Lazer")
    @patch("app.comandos.gasto.regra_aprendida", return_value=None)
    def test_ia_sugere_quando_regras_nao_acham(self, _regra, ia_categoria, *_):
        resposta = processar_mensagem(USUARIO, "/gasto 50 boliche")
        self.assertIn("Categoria: Lazer", resposta.texto)
        ia_categoria.assert_called_once()

    @patch("app.comandos.gasto.ia.sugerir_categoria", return_value=None)
    @patch("app.comandos.gasto.regra_aprendida", return_value=None)
    def test_sem_sugestao_abre_lista_de_categorias(self, _regra, _ia, _conta, _lista, _abrir, salvar, *_):
        resposta = processar_mensagem(USUARIO, "/gasto 50 boliche")
        self.assertIn("Qual a categoria?", resposta.texto)
        self.assertEqual(len(resposta.lista), 10)
        self.assertEqual(salvar.call_args.args[2]["passo"], "categoria")

    @patch("app.comandos.gasto.ia.entender_gasto", return_value={"valor": "50", "descricao": "bar"})
    @patch("app.comandos.gasto.regra_aprendida", return_value=None)
    def test_frase_dificil_usa_ia(self, _regra, entender, *_):
        resposta = processar_mensagem(USUARIO, "ontem gastei uns 50 conto lá no bar")
        entender.assert_called_once()
        self.assertIn("R$ 50,00", resposta.texto)
        self.assertIn("Restaurante", resposta.texto)

    @patch("app.comandos.gasto.ia.entender_gasto")
    def test_frase_comum_nao_chama_ia(self, entender, *_):
        self.assertIn("/ajuda", processar_mensagem(USUARIO, "bom dia"))
        entender.assert_not_called()

    def test_gasto_mal_escrito(self, *_):
        self.assertIn("/gasto 45,90 mercado", processar_mensagem(USUARIO, "/gasto mercado"))


@patch("app.comandos.gasto.limpar_estado")
@patch("app.comandos.gasto.salvar_estado")
@patch("app.comandos.gasto.abrir_lista", side_effect=lista_falsa)
@patch("app.comandos.gasto.listar_categorias", return_value=CATEGORIAS)
@patch("app.comandos.gasto.conta_do_usuario", return_value=CONTA)
class TestConfirmacaoGasto(unittest.TestCase):
    DADOS = {
        "passo": "confirmar", "valor": "45.90", "descricao": "racao", "escopo": "conjunto",
        "categoria_id": "2", "categoria_nome": "Mercado",
    }

    @patch("app.comandos.gasto.gravar_gasto")
    def test_sim_grava(self, gravar, *_):
        self.assertIn("Anotado: R$ 45,90 em Mercado", continuar_gasto(USUARIO, self.DADOS, "Sim"))
        gravar.assert_called_once_with("conta-1", "usuario-1", self.DADOS, "2")

    @patch("app.comandos.gasto.gravar_gasto")
    def test_corrigir_oferece_valor_e_categoria(self, gravar, _conta, _lista, _abrir, salvar, _limpar):
        resposta = continuar_gasto(USUARIO, self.DADOS, "Corrigir")
        self.assertEqual(resposta.botoes, ("Valor", "Categoria"))
        gravar.assert_not_called()
        self.assertEqual(salvar.call_args.args[2]["passo"], "corrigir")

    @patch("app.comandos.gasto.gravar_gasto")
    def test_corrigir_categoria_abre_a_lista(self, gravar, _conta, _lista, _abrir, salvar, _limpar):
        dados = {**self.DADOS, "passo": "corrigir"}
        resposta = continuar_gasto(USUARIO, dados, "Categoria")
        self.assertEqual(len(resposta.lista), 10)
        self.assertIn("Qual a categoria?", resposta.texto)
        self.assertEqual(salvar.call_args.args[2]["passo"], "categoria")
        gravar.assert_not_called()

    @patch("app.comandos.gasto.gravar_gasto")
    def test_corrigir_valor_pede_o_valor_e_volta_para_confirmar(self, gravar, _conta, _lista, _abrir, salvar, _limpar):
        dados = {**self.DADOS, "passo": "corrigir"}
        self.assertIn("Qual o valor correto?", continuar_gasto(USUARIO, dados, "Valor"))
        self.assertEqual(salvar.call_args.args[2]["passo"], "valor")
        resposta = continuar_gasto(USUARIO, {**self.DADOS, "passo": "valor"}, "50,5")
        self.assertEqual(resposta.botoes, ("Sim", "Corrigir"))
        self.assertIn("R$ 50,50", resposta.texto)
        self.assertEqual(salvar.call_args.args[2]["valor"], "50.50")
        self.assertEqual(salvar.call_args.args[2]["passo"], "confirmar")
        gravar.assert_not_called()

    def test_valor_invalido_pergunta_de_novo(self, *_):
        resposta = continuar_gasto(USUARIO, {**self.DADOS, "passo": "valor"}, "muito")
        self.assertIn("Não entendi o valor", resposta)

    @patch("app.comandos.gasto.salvar_regra")
    @patch("app.comandos.gasto.gravar_gasto")
    def test_categoria_da_lista_grava_e_aprende(self, gravar, regra, *_):
        dados = {**self.DADOS, "passo": "categoria", "pagina": None}
        resposta = continuar_gasto(USUARIO, dados, "cat:7")
        self.assertIn("em Pets", resposta)
        self.assertIn("Aprendi", resposta)
        gravar.assert_called_once_with("conta-1", "usuario-1", dados, "7")
        regra.assert_called_once_with("conta-1", "usuario-1", "racao", "7")

    @patch("app.comandos.gasto.gravar_gasto")
    def test_categoria_digitada_tambem_funciona(self, gravar, *_):
        dados = {**self.DADOS, "passo": "categoria", "pagina": None}
        with patch("app.comandos.gasto.salvar_regra"):
            self.assertIn("em Lazer", continuar_gasto(USUARIO, dados, "lazer"))

    @patch("app.comandos.gasto.gravar_gasto")
    def test_categoria_invalida_mostra_a_lista_de_novo(self, gravar, *_):
        dados = {**self.DADOS, "passo": "categoria", "pagina": None}
        resposta = continuar_gasto(USUARIO, dados, "xyz")
        self.assertIn("Não achei", resposta.texto)
        self.assertTrue(resposta.lista)
        gravar.assert_not_called()

    def test_outras_e_mais_trocam_a_pagina(self, _conta, _lista, _abrir, salvar, _limpar):
        dados = {**self.DADOS, "passo": "categoria", "pagina": None}
        resposta = continuar_gasto(USUARIO, dados, "acao:outras")
        self.assertEqual(salvar.call_args.args[2]["pagina"], 0)
        self.assertEqual(resposta.lista[-1][1], "➕ Nova categoria")
        self.assertNotIn("Moradia", [t for _, t, _ in resposta.lista])  # Moradia é das principais
        continuar_gasto(USUARIO, {**dados, "pagina": 0}, "acao:mais")
        self.assertEqual(salvar.call_args.args[2]["pagina"], 1)

    @patch("app.comandos.gasto.iniciar_nova", return_value="Qual o nome?")
    def test_nova_categoria_leva_o_gasto_junto(self, iniciar, *_):
        dados = {**self.DADOS, "passo": "categoria", "pagina": None}
        self.assertEqual(continuar_gasto(USUARIO, dados, "acao:nova"), "Qual o nome?")
        iniciar.assert_called_once_with(USUARIO, retorno=dados)


@patch("app.comandos.categorias.limpar_estado")
@patch("app.comandos.categorias.salvar_estado")
@patch("app.comandos.categorias.listar_categorias", return_value=CATEGORIAS)
@patch("app.comandos.categorias.conta_do_usuario", return_value=CONTA)
class TestNovaCategoria(unittest.TestCase):
    def test_nome_ja_existente(self, *_):
        resposta = continuar_nova(USUARIO, {"passo": "nome", "retorno": None}, "pets")
        self.assertIn("já existe", resposta)

    def test_nome_pedido_e_tipo_por_botoes(self, _conta, _lista, salvar, _limpar):
        resposta = continuar_nova(USUARIO, {"passo": "nome", "retorno": None}, "academia")
        self.assertEqual(resposta.botoes, ("Fixo", "Variável", "Outro tipo…"))
        self.assertEqual(salvar.call_args.args[2]["nome"], "Academia")
        self.assertEqual(salvar.call_args.args[2]["passo"], "tipo")

    def test_outro_tipo_mostra_os_demais(self, _conta, _lista, salvar, _limpar):
        dados = {"passo": "tipo", "nome": "Academia", "retorno": None}
        resposta = continuar_nova(USUARIO, dados, "Outro tipo…")
        self.assertEqual(resposta.botoes, ("Assinatura", "Investimento", "Reserva emergência"))
        self.assertEqual(salvar.call_args.args[2]["passo"], "tipo2")

    @patch("app.comandos.categorias.criar_categoria", return_value="99")
    def test_tipo_cria_a_categoria(self, criar, _conta, _lista, _salvar, limpar):
        dados = {"passo": "tipo", "nome": "Academia", "retorno": None}
        self.assertEqual(
            continuar_nova(USUARIO, dados, "Variável"), "Categoria Academia (Variável) criada."
        )
        criar.assert_called_once_with("conta-1", "usuario-1", "Academia", "Variável")
        limpar.assert_called_once_with(USUARIO)

    @patch("app.comandos.categorias.criar_categoria", return_value="99")
    def test_botao_reserva_emergencia(self, criar, *_):
        dados = {"passo": "tipo2", "nome": "Cofre", "retorno": None}
        continuar_nova(USUARIO, dados, "Reserva emergência")
        criar.assert_called_once_with("conta-1", "usuario-1", "Cofre", "Reserva de emergência")

    def test_tipo_invalido_pergunta_de_novo(self, *_):
        dados = {"passo": "tipo", "nome": "Academia", "retorno": None}
        resposta = continuar_nova(USUARIO, dados, "talvez")
        self.assertEqual(resposta.botoes, ("Fixo", "Variável", "Outro tipo…"))

    @patch("app.comandos.gasto.salvar_regra")
    @patch("app.comandos.gasto.gravar_gasto")
    @patch("app.comandos.categorias.criar_categoria", return_value="99")
    def test_criada_durante_um_gasto_ja_registra_o_gasto(self, _criar, gravar, regra, *_):
        gasto = {"valor": "45.90", "descricao": "boliche", "escopo": "conjunto"}
        dados = {"passo": "tipo", "nome": "Academia", "retorno": gasto}
        resposta = continuar_nova(USUARIO, dados, "Variável")
        self.assertIn("Categoria Academia (Variável) criada.", resposta)
        self.assertIn("Anotado: R$ 45,90 em Academia", resposta)
        gravar.assert_called_once_with("conta-1", "usuario-1", gasto, "99")
        regra.assert_called_once_with("conta-1", "usuario-1", "boliche", "99")


@patch("app.comandos.categorias.limpar_estado")
@patch("app.comandos.categorias.salvar_estado")
@patch("app.comandos.categorias.mais_usadas", return_value=["7"])
@patch("app.comandos.categorias.listar_categorias", return_value=CATEGORIAS)
@patch("app.comandos.categorias.conta_do_usuario", return_value=CONTA)
class TestComandoCategorias(unittest.TestCase):
    def test_abre_a_lista(self, _conta, _lista, _usadas, salvar, _limpar):
        from app.comandos.categorias import comando_categorias

        resposta = comando_categorias(USUARIO, "")
        self.assertEqual(resposta.lista[0][1], "Pets")  # a mais usada vem primeiro
        self.assertEqual(len(resposta.lista), 10)
        self.assertIn("Variável:", resposta.texto)
        salvar.assert_called_once_with(USUARIO, "categorias", {"pagina": None})

    @patch("app.comandos.categorias.criar_categoria")
    def test_criar_por_texto_continua_funcionando(self, criar, *_):
        from app.comandos.categorias import comando_categorias

        self.assertEqual(
            comando_categorias(USUARIO, "criar Academia variavel"),
            "Categoria Academia (Variável) criada.",
        )
        criar.assert_called_once_with("conta-1", "usuario-1", "Academia", "Variável")

    def test_tocar_numa_categoria_mostra_o_tipo(self, _conta, _lista, _usadas, _salvar, limpar):
        self.assertEqual(
            continuar_categorias(USUARIO, {"pagina": None}, "cat:7"), "Pets é do tipo Variável."
        )
        limpar.assert_called_once_with(USUARIO)

    @patch("app.comandos.categorias.iniciar_nova", return_value="Qual o nome?")
    def test_nova_categoria_pela_lista(self, iniciar, *_):
        self.assertEqual(continuar_categorias(USUARIO, {"pagina": None}, "acao:nova"), "Qual o nome?")
        iniciar.assert_called_once_with(USUARIO)

    def test_outras_abre_o_resto(self, _conta, _lista, _usadas, salvar, _limpar):
        resposta = continuar_categorias(USUARIO, {"pagina": None}, "acao:outras")
        self.assertEqual(salvar.call_args.args[2], {"pagina": 0})
        self.assertEqual(resposta.lista[-1][1], "➕ Nova categoria")


class TestWhatsApp(unittest.TestCase):
    def test_message_text_de_lista_devolve_o_id(self):
        mensagem = {"type": "interactive", "interactive": {
            "type": "list_reply", "list_reply": {"id": "cat:7", "title": "Pets"}}}
        self.assertEqual(message_text(mensagem), "cat:7")

    def test_message_text_de_botao_devolve_o_titulo(self):
        mensagem = {"type": "interactive", "interactive": {
            "type": "button_reply", "button_reply": {"id": "valor", "title": "Valor"}}}
        self.assertEqual(message_text(mensagem), "Valor")

    def test_message_text_de_texto_e_de_foto(self):
        self.assertEqual(message_text({"type": "text", "text": {"body": "oi"}}), "oi")
        self.assertIsNone(message_text({"type": "image"}))

    @patch("app.whatsapp._post_message")
    def test_send_list_monta_o_pedido_da_meta(self, post):
        longa = Categoria("1", "Um nome de categoria bem comprido", "Variável")
        resposta = lista_categorias("Qual a categoria?", [longa] + CATEGORIAS[:3], [])
        send_list("5511", resposta)
        enviado = post.call_args.args[0]["interactive"]
        self.assertEqual(enviado["type"], "list")
        self.assertEqual(enviado["body"]["text"], "Qual a categoria?")
        self.assertEqual(enviado["action"]["button"], "Escolher categoria")
        linhas = enviado["action"]["sections"][0]["rows"]
        self.assertLessEqual(len(linhas), 10)
        self.assertEqual(linhas[0]["id"], "cat:1")
        self.assertLessEqual(len(linhas[0]["title"]), 24)
        self.assertNotIn("description", linhas[-1])  # "Nova categoria" não tem descrição


@patch("app.comandos.desfazer.limpar_estado")
@patch("app.comandos.desfazer.conta_do_usuario", return_value=CONTA)
class TestDesfazer(unittest.TestCase):
    REGISTRO = SimpleNamespace(
        id="t1", transaction_type="expense", amount=Decimal("45.90"),
        description="mercado", transaction_date=date(2026, 10, 16), categoria="Mercado",
    )

    def test_descrever(self, *_):
        self.assertEqual(descrever(self.REGISTRO), "Gasto de R$ 45,90 — mercado (Mercado), 16/10/2026")

    @patch("app.comandos.desfazer.salvar_estado")
    @patch("app.comandos.desfazer.ultimo_registro")
    @patch("app.comandos.garantir_usuario", return_value=False)
    @patch("app.comandos.status_acesso", return_value="ativo")
    @patch("app.comandos.limpar_estado")
    def test_pede_confirmacao(self, _l, _s, _g, ultimo, salvar, *_):
        ultimo.return_value = self.REGISTRO
        resposta = processar_mensagem(USUARIO, "/desfazer")
        self.assertEqual(resposta.botoes, ("Sim", "Não"))
        self.assertIn("16/10/2026", resposta.texto)
        self.assertEqual(salvar.call_args.args[2]["id"], "t1")

    def test_nao_mantem(self, *_):
        self.assertIn("mantive", continuar_desfazer(USUARIO, {"id": "t1", "descricao": "x"}, "Não"))


class TestIA(unittest.TestCase):
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""})
    def test_sem_chave_devolve_none(self):
        self.assertIsNone(ia.chamar_ia("sistema", "oi"))

    @patch("app.ia.chamar_ia", return_value='Claro: {"valor": "50,00", "descricao": "bar"}')
    def test_entender_gasto_le_json(self, _):
        self.assertEqual(ia.entender_gasto("x"), {"valor": "50,00", "descricao": "bar"})

    @patch("app.ia.chamar_ia", return_value='{"valor": null}')
    def test_entender_gasto_sem_valor(self, _):
        self.assertIsNone(ia.entender_gasto("x"))


if __name__ == "__main__":
    unittest.main()
