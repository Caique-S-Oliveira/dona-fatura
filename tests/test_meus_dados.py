"""/meus_dados (planilha), aviso de privacidade [Entendi] e apagar sem tirar o número.

Usa o banco SQLite em memória de tests/test_casal.py (nunca o banco real).
"""
import io
import unittest
import zipfile
from unittest.mock import Mock, patch
from xml.etree import ElementTree

from app import xlsx
from app.comandos import aviso, processar_comprovante, processar_mensagem
from app.comandos.categorias import Categoria
from app.comandos.privacidade import _apagar
from app.comandos.resposta import Resposta
from tests import test_casal

ANA, BIA = test_casal.ANA, test_casal.BIA


def ler_abas(conteudo: bytes) -> dict[str, list[list[str]]]:
    """Abre o .xlsx gerado e devolve {aba: linhas de texto}."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        assert z.testzip() is None
        livro = ElementTree.fromstring(z.read("xl/workbook.xml"))
        nomes = [s.get("name") for s in livro.find("m:sheets", ns)]
        abas = {}
        for i, nome in enumerate(nomes, 1):
            folha = ElementTree.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
            abas[nome] = [
                ["".join(c.itertext()) for c in linha] for linha in folha.find("m:sheetData", ns)
            ]
    return abas


class TestXlsx(unittest.TestCase):
    def test_gera_abas_e_celulas(self):
        abas = ler_abas(xlsx.montar([("A", ["x", "y"], [["oi & <tchau>", 12.5], [None, True]])]))
        self.assertEqual(abas["A"][0], ["x", "y"])
        self.assertEqual(abas["A"][1], ["oi & <tchau>", "12.5"])
        self.assertEqual(abas["A"][2][1], "Sim")

    def test_texto_com_formula_vira_texto(self):
        abas = ler_abas(xlsx.montar([("A", ["x"], [["=1+1"], ["@soma"]])]))
        self.assertEqual([l[0] for l in abas["A"][1:]], ["'=1+1", "'@soma"])


class TestMeusDados(test_casal.BancoDeTeste):
    def test_planilha_nao_mostra_o_meu_do_parceiro(self):
        self.formar_casal("pessoal")
        cat = self.categoria(ANA, "Mercado", "Variável")
        self.registrar(ANA, 40, "meu", categoria=cat, descricao="meu-da-ana")
        self.registrar(ANA, 30, "conjunto", categoria=cat, descricao="junto")
        self.registrar(BIA, 99, "meu", categoria=cat, descricao="segredo-da-bia")
        resposta = processar_mensagem(ANA, "/meus_dados")
        self.assertIsInstance(resposta, Resposta)
        nome, conteudo = resposta.documento
        self.assertTrue(nome.endswith(".xlsx"))
        abas = ler_abas(conteudo)
        descricoes = [linha[4] for linha in abas["Transações"][1:]]
        self.assertIn("meu-da-ana", descricoes)
        self.assertIn("junto", descricoes)
        self.assertNotIn("segredo-da-bia", descricoes)
        self.assertNotIn("segredo-da-bia", str(abas))
        self.assertIn(["Número de WhatsApp", ANA], abas["Seus dados"])
        self.assertIn("Aviso", abas)

    def test_conta_individual_sem_dados_gera_planilha(self):
        self.cadastrar(ANA, "Ana")
        abas = ler_abas(processar_mensagem(ANA, "/meus_dados").documento[1])
        self.assertEqual(len(abas["Transações"]), 1)  # só o cabeçalho
        self.assertNotIn("Aviso", abas)


class TestAviso(test_casal.BancoDeTeste):
    def setUp(self):
        super().setUp()
        mercado = Categoria("cat-mercado", "Mercado", "Variável")
        for nome, novo in (
            ("listar_categorias", lambda account_id: [mercado]),
            ("sugerir", lambda *args: mercado),
        ):
            patcher = patch(f"app.comandos.gasto.{nome}", novo)
            patcher.start()
            self.addCleanup(patcher.stop)

    def cadastrar_sem_aviso(self):
        self.cadastrar(ANA, "Ana")
        self.sql("UPDATE users SET privacidade_aceita_em = NULL")

    def test_primeiro_gasto_pede_entendi_e_depois_refaz(self):
        self.cadastrar_sem_aviso()
        primeira = processar_mensagem(ANA, "/gasto 45,90 mercado")
        self.assertEqual(primeira.botoes, ("Entendi",))
        self.assertEqual(self.sql("SELECT count(*) FROM transactions").scalar(), 0)  # nada registrado ainda
        segunda = processar_mensagem(ANA, "Entendi")
        self.assertIn("45,90", segunda.texto)  # o gasto original seguiu o fluxo normal
        self.assertTrue(aviso.aceitou(ANA))
        self.assertIsNotNone(self.sql("SELECT privacidade_aceita_em FROM users").scalar())

    def test_frase_livre_tambem_pede(self):
        self.cadastrar_sem_aviso()
        self.assertEqual(processar_mensagem(ANA, "gastei 45 no mercado").botoes, ("Entendi",))

    def test_resposta_estranha_nao_libera(self):
        self.cadastrar_sem_aviso()
        processar_mensagem(ANA, "/gasto 10 pao")
        self.assertEqual(processar_mensagem(ANA, "talvez").botoes, ("Entendi",))
        self.assertFalse(aviso.aceitou(ANA))

    def test_depois_de_aceitar_nao_pergunta_de_novo(self):
        self.cadastrar(ANA, "Ana")  # já cadastrado com aviso aceito
        resposta = processar_mensagem(ANA, "/gasto 10 pao")
        self.assertNotEqual(getattr(resposta, "botoes", ()), ("Entendi",))

    def test_comandos_de_consulta_nao_pedem_aviso(self):
        self.cadastrar_sem_aviso()
        resposta = processar_mensagem(ANA, "/ajuda")
        self.assertNotIn("Entendi", str(getattr(resposta, "botoes", "")))

    def test_comprovante_sem_aviso_nao_baixa_o_arquivo(self):
        self.cadastrar_sem_aviso()
        baixar = Mock()
        resposta = processar_comprovante(ANA, "image/jpeg", baixar)
        self.assertEqual(resposta.botoes, ("Entendi",))
        baixar.assert_not_called()
        final = processar_mensagem(ANA, "Entendi")
        self.assertIn("de novo", final.texto)


class TestApagarMantemNumero(test_casal.BancoDeTeste):
    def setUp(self):
        super().setUp()
        for comando in (
            "CREATE TABLE sent_alerts (account_id TEXT, user_id TEXT)",
            "CREATE TABLE reminder_log (user_id TEXT)",
            "CREATE TABLE processed_messages (sender_phone_number TEXT)",
        ):
            self.sql(comando)

    def test_apaga_dados_e_mantem_o_numero(self):
        self.cadastrar(ANA, "Ana", 4500)
        user, conta = self.ids(ANA)
        cat = self.categoria(ANA, "Mercado", "Variável")
        self.registrar(ANA, 40, "meu", categoria=cat)
        self.sql("INSERT INTO pending_notices (user_id, message) VALUES (:u, 'oi')", u=user)
        self.sql("INSERT INTO reminder_log (user_id) VALUES (:u)", u=user)
        self.assertTrue(_apagar(ANA, user, conta))
        self.assertEqual(self.sql("SELECT count(*) FROM transactions").scalar(), 0)
        self.assertEqual(self.sql("SELECT count(*) FROM pending_notices").scalar(), 0)
        self.assertEqual(self.sql("SELECT count(*) FROM reminder_log").scalar(), 0)
        linha = self.sql("SELECT phone_number, access_status, display_name FROM users").one()
        self.assertEqual(linha.phone_number, ANA)
        self.assertEqual(linha.access_status, "ativo")
        self.assertIsNone(linha.display_name)


if __name__ == "__main__":
    unittest.main()
