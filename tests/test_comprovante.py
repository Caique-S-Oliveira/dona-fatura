import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from app import ia
from app.comandos import processar_comprovante
from app.comandos.categorias import PADRAO, Categoria
from app.comandos.comprovante import ler_data, montar_dados, receber_comprovante
from app.comandos.gasto import registrar
from app.comandos.resposta import Resposta
from app.whatsapp import message_media

USUARIO = "5511988887777"
CATEGORIAS = [Categoria(str(i), nome, tipo) for i, (nome, tipo) in enumerate(PADRAO.items(), 1)]
CONTA = ("usuario-1", "conta-1")
EXTRAIDO = {"valor": "45,90", "data": "10/10/2026", "favorecido": "Padaria Pão Quente"}


class TestLeitura(unittest.TestCase):
    def test_ler_data(self):
        self.assertEqual(ler_data("10/10/2026"), "2026-10-10")
        self.assertEqual(ler_data("2026-10-10"), "2026-10-10")
        self.assertIsNone(ler_data("31/02/2026"))
        self.assertIsNone(ler_data("10/10/2999"))  # futura: vale hoje
        self.assertIsNone(ler_data(None))

    def test_montar_dados(self):
        dados = montar_dados(EXTRAIDO)
        self.assertEqual(dados["valor"], "45.90")
        self.assertEqual(dados["descricao"], "Padaria Pão Quente")
        self.assertEqual(dados["favorecido"], "Padaria Pão Quente")
        self.assertEqual(dados["data"], "2026-10-10")
        self.assertEqual(dados["fonte"], "receipt")
        self.assertNotIn("aprender", dados)

    def test_sem_favorecido_nao_aprende(self):
        dados = montar_dados({"valor": "10", "data": None, "favorecido": None})
        self.assertEqual(dados["descricao"], "Comprovante")
        self.assertFalse(dados["aprender"])
        self.assertNotIn("data", dados)

    def test_valor_invalido(self):
        self.assertIsNone(montar_dados({"valor": "abc", "data": None, "favorecido": "x"}))
        self.assertIsNone(montar_dados({"valor": "0", "data": None, "favorecido": "x"}))

    def test_message_media(self):
        foto = {"type": "image", "image": {"id": "m1", "mime_type": "image/jpeg"}}
        self.assertEqual(message_media(foto), ("m1", "image/jpeg"))
        self.assertIsNone(message_media({"type": "text", "text": {"body": "oi"}}))
        self.assertIsNone(message_media({"type": "image", "image": {}}))


@patch("app.comandos.gasto.salvar_estado")
@patch("app.comandos.gasto.listar_categorias", return_value=CATEGORIAS)
@patch("app.comandos.comprovante.conta_do_usuario", return_value=CONTA)
@patch("app.comandos.gasto.deve_perguntar_escopo", new=lambda account_id: False)  # sem casal, sem banco
class TestFluxoComprovante(unittest.TestCase):
    @patch("app.comandos.gasto.sugerir", return_value=CATEGORIAS[1])  # Mercado
    @patch("app.comandos.comprovante.ia.ler_comprovante", return_value=EXTRAIDO)
    def test_le_sugere_e_pede_confirmacao(self, _ler, _sugerir, _conta, _lista, salvar):
        resposta = receber_comprovante(USUARIO, "image/jpeg", lambda: b"foto")
        self.assertIsInstance(resposta, Resposta)
        self.assertEqual(resposta.botoes, ("Sim", "Corrigir"))
        self.assertIn("R$ 45,90", resposta.texto)
        self.assertIn("10/10/2026", resposta.texto)
        self.assertIn("Categoria: Mercado", resposta.texto)
        guardado = salvar.call_args.args[2]
        self.assertEqual(guardado["passo"], "confirmar")
        self.assertNotIn("foto", str(guardado))  # o arquivo não vai para o estado

    @patch("app.comandos.gasto.sugerir", return_value=None)
    @patch("app.comandos.comprovante.ia.ler_comprovante", return_value=EXTRAIDO)
    @patch("app.comandos.gasto.salvar_estado")
    @patch("app.comandos.gasto.conta_do_usuario", return_value=CONTA)
    @patch("app.comandos.gasto.abrir_lista")
    def test_sem_sugestao_abre_a_lista(self, abrir, _gconta, _gsalvar, _ler, _sugerir, *_):
        abrir.return_value = Resposta("Qual a categoria?")
        receber_comprovante(USUARIO, "application/pdf", lambda: b"pdf")
        abrir.assert_called_once()

    @patch("app.comandos.comprovante.ia.ler_comprovante", return_value=None)
    def test_ia_nao_entendeu(self, _ler, *_):
        self.assertIn("Não consegui ler", receber_comprovante(USUARIO, "image/png", lambda: b"x"))

    def test_tipo_nao_aceito_nem_baixa(self, *_):
        baixar = MagicMock()
        self.assertIn("foto", receber_comprovante(USUARIO, "video/mp4", baixar))
        baixar.assert_not_called()

    def test_arquivo_grande_demais(self, *_):
        self.assertIn("Não consegui ler", receber_comprovante(USUARIO, "image/png", lambda: None))


class TestAcesso(unittest.TestCase):
    @patch("app.comandos.garantir_usuario", return_value=False)
    @patch("app.comandos.eh_admin", return_value=False)
    @patch("app.comandos.status_acesso", return_value="pendente")
    def test_pendente_nao_baixa_nem_chama_ia(self, *_):
        baixar = MagicMock()
        processar_comprovante(USUARIO, "image/png", baixar)
        baixar.assert_not_called()

    @patch("app.comandos.receber_comprovante", return_value="ok")
    @patch("app.comandos.ler_estado", return_value=None)
    @patch("app.comandos.limpar_estado")
    @patch("app.comandos.garantir_usuario", return_value=False)
    @patch("app.comandos.eh_admin", return_value=False)
    @patch("app.comandos.status_acesso", return_value="ativo")
    def test_ativo_le_o_comprovante(self, _s, _a, _g, limpar, _estado, receber):
        self.assertEqual(processar_comprovante(USUARIO, "image/png", None), "ok")
        limpar.assert_called_once_with(USUARIO)


class TestGravacao(unittest.TestCase):
    DADOS = {"valor": "45.90", "descricao": "Padaria", "favorecido": "Padaria", "escopo": "conjunto",
             "fonte": "receipt", "data": "2026-10-10", "categoria_id": "2"}

    @patch("app.comandos.gasto.salvar_regra")
    @patch("app.comandos.gasto.gravar_gasto")
    def test_corrigir_categoria_grava_a_regra_do_favorecido(self, gravar, regra):
        texto = registrar("conta-1", "usuario-1", self.DADOS, CATEGORIAS[6])  # Pets
        self.assertIn("Aprendi", texto)
        regra.assert_called_once_with("conta-1", "usuario-1", "Padaria", "7")

    @patch("app.comandos.gasto.salvar_regra")
    @patch("app.comandos.gasto.gravar_gasto")
    def test_sem_favorecido_nao_grava_regra(self, gravar, regra):
        registrar("conta-1", "usuario-1", {**self.DADOS, "aprender": False}, CATEGORIAS[6])
        regra.assert_not_called()

    @patch("app.comandos.gasto.get_engine")
    def test_gravar_usa_data_favorecido_e_fonte_do_comprovante(self, motor):
        from app.comandos.gasto import gravar_gasto

        gravar_gasto("conta-1", "usuario-1", self.DADOS, "2")
        executar = motor.return_value.begin.return_value.__enter__.return_value.execute
        parametros = executar.call_args.args[1]
        self.assertEqual(parametros["data"], "2026-10-10")
        self.assertEqual(parametros["favorecido"], "Padaria")
        self.assertEqual(parametros["fonte"], "receipt")


class TestIA(unittest.TestCase):
    @patch("app.ia.chamar_ia", return_value='{"valor": "45,90", "data": "10/10/2026", "favorecido": "Padaria"}')
    def test_ler_comprovante_manda_imagem_ou_pdf(self, chamar):
        ia.ler_comprovante(b"abc", "image/png")
        self.assertEqual(chamar.call_args.args[1][0]["type"], "image")
        ia.ler_comprovante(b"abc", "application/pdf")
        self.assertEqual(chamar.call_args.args[1][0]["type"], "document")

    @patch("app.ia.chamar_ia", return_value='{"valor": null}')
    def test_nao_e_comprovante(self, _):
        self.assertIsNone(ia.ler_comprovante(b"abc", "image/png"))


if __name__ == "__main__":
    unittest.main()
