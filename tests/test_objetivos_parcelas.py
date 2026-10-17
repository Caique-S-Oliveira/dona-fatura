import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app import financas
from app.comandos import COMANDOS_COM_USUARIO
from app.comandos.objetivos import (
    Objetivo,
    achar_objetivo,
    comando_objetivos,
    continuar_gerir,
    continuar_objetivo,
    descrever as descrever_objetivo,
    frase_de_aporte,
    ler_aporte,
    ler_novo,
    ler_prazo,
)
from app.comandos.parcelas import (
    atualizar_parcela,
    comando_parcelas,
    continuar_gerir as parcelas_gerir,
    continuar_parcela,
    ler_nova,
    montar_lista,
)
from app.comandos.resposta import Resposta
from app.financas import Parcelamento

D = Decimal
HOJE = date(2026, 10, 16)
USUARIO = "5511988887777"


class TestCalculos(unittest.TestCase):
    def test_somar_meses(self):
        self.assertEqual(financas.somar_meses(date(2026, 10, 16), 1), date(2026, 11, 16))
        self.assertEqual(financas.somar_meses(date(2026, 12, 5), 1), date(2027, 1, 5))
        self.assertEqual(financas.somar_meses(date(2026, 1, 31), 1, 31), date(2026, 2, 28))
        self.assertEqual(financas.somar_meses(date(2026, 3, 20), -3), date(2025, 12, 20))

    def test_proximo_dia_e_sempre_depois_de_hoje(self):
        self.assertEqual(financas.proximo_dia(20, HOJE), date(2026, 10, 20))
        self.assertEqual(financas.proximo_dia(16, HOJE), date(2026, 11, 16))
        self.assertEqual(financas.proximo_dia(5, HOJE), date(2026, 11, 5))

    def test_guardar_por_mes_arredonda_para_cima(self):
        # 16/10 até 31/12: outubro, novembro e dezembro = 3 meses
        self.assertEqual(financas.meses_ate(date(2026, 12, 31), HOJE), 3)
        self.assertEqual(financas.guardar_por_mes(D("1000"), date(2026, 12, 31), HOJE), D("333.34"))
        self.assertEqual(financas.meses_ate(date(2026, 12, 10), HOJE), 2)
        self.assertEqual(financas.meses_ate(date(2026, 10, 31), HOJE), 1)

    def test_parcelas_pagas_e_restantes(self):
        p = Parcelamento("Geladeira", D("250"), 10, date(2026, 8, 20), 20)  # 20/08 ... 20/05/2027
        self.assertEqual(p.pagas(HOJE), 2)  # 20/08 e 20/09
        self.assertEqual(p.restantes(HOJE), 8)
        self.assertEqual(p.falta_pagar(HOJE), D("2000"))
        self.assertEqual(p.proximo_vencimento(HOJE), date(2026, 10, 20))

    def test_parcelas_terminadas(self):
        p = Parcelamento("TV", D("100"), 3, date(2026, 5, 10), 10)
        self.assertEqual(p.restantes(HOJE), 0)
        self.assertIsNone(p.proximo_vencimento(HOJE))

    def test_a_vencer_so_conta_o_que_vence_depois_de_hoje_neste_mes(self):
        vence = Parcelamento("A", D("250"), 10, date(2026, 8, 20), 20)  # 20/10: ainda vence
        passou = Parcelamento("B", D("100"), 10, date(2026, 8, 10), 10)  # 10/10: já venceu
        fica_pro_mes_que_vem = Parcelamento("C", D("80"), 5, date(2026, 8, 5), 5)  # próxima 05/11
        acabou = Parcelamento("D", D("70"), 2, date(2026, 5, 20), 20)
        self.assertEqual(
            financas.valor_parcelas_a_vencer([vence, passou, fica_pro_mes_que_vem, acabou], HOJE), D("250")
        )

    def test_vencimento_dia_31_usa_o_ultimo_dia_do_mes(self):
        p = Parcelamento("X", D("10"), 4, date(2026, 8, 31), 31)
        self.assertEqual(p.vencimento(2), date(2026, 9, 30))
        self.assertEqual(p.vencimento(3), date(2026, 10, 31))


class TestObjetivosRegras(unittest.TestCase):
    def test_prazo(self):
        self.assertEqual(ler_prazo("12/2026"), date(2026, 12, 31))
        self.assertEqual(ler_prazo("15/03/2027"), date(2027, 3, 15))
        self.assertIsNone(ler_prazo("13/2026"))
        self.assertIsNone(ler_prazo("amanhã"))

    def test_novo(self):
        self.assertEqual(ler_novo("Viagem Europa 5000 12/2026", HOJE), ("Viagem Europa", D("5000.00"), date(2026, 12, 31)))
        self.assertIn("/objetivos novo", ler_novo("Viagem", HOJE))
        self.assertIn("futura", ler_novo("Viagem 5000 09/2026", HOJE))

    def test_aporte(self):
        self.assertEqual(ler_aporte("guardei 200 viagem"), (D("200.00"), "viagem"))
        self.assertEqual(ler_aporte("Guardei R$ 1.200,50 na reserva"), (D("1200.50"), "reserva"))
        self.assertEqual(ler_aporte("juntei 50 reais para a viagem"), (D("50.00"), "a viagem"))
        self.assertEqual(ler_aporte("guardei 200"), (D("200.00"), ""))
        self.assertIsNone(ler_aporte("gastei 200 viagem"))

    def test_achar_objetivo(self):
        viagem = Objetivo("1", "Viagem Europa", D("5000"), date(2026, 12, 31), D("0"))
        carro = Objetivo("2", "Carro", D("9000"), date(2027, 6, 30), D("0"))
        self.assertEqual(achar_objetivo([viagem, carro], "viagem").id, "1")
        self.assertEqual(achar_objetivo([viagem, carro], "a viagem europa").id, "1")
        self.assertIsNone(achar_objetivo([viagem, carro], "casa"))
        self.assertIsNone(achar_objetivo([viagem, carro], ""))  # duas opções: não chuta
        self.assertEqual(achar_objetivo([carro], "").id, "2")

    def test_descrever(self):
        viagem = Objetivo("1", "Viagem", D("5000"), date(2026, 12, 31), D("2000"))
        texto = descrever_objetivo(viagem, HOJE)
        self.assertIn("R$ 2.000,00 de R$ 5.000,00 (40%)", texto)
        self.assertIn("Faltam R$ 3.000,00 até 31/12/2026: guarde R$ 1.000,00 por mês", texto)
        pronto = Objetivo("1", "Viagem", D("5000"), date(2026, 12, 31), D("5200"))
        self.assertIn("alcançado", descrever_objetivo(pronto, HOJE))
        atrasado = Objetivo("1", "Viagem", D("5000"), date(2026, 9, 30), D("1000"))
        self.assertIn("já passou", descrever_objetivo(atrasado, HOJE))


class TestParcelasRegras(unittest.TestCase):
    def test_nova_simples(self):
        p, escopo, pagas = ler_nova("Geladeira 250 10x", HOJE)
        self.assertEqual((p.nome, p.valor, p.total, p.dia), ("Geladeira", D("250.00"), 10, 16))
        self.assertEqual(p.primeiro_vencimento, date(2026, 11, 16))
        self.assertEqual((escopo, pagas), ("conjunto", 0))

    def test_nova_com_dia_pagas_e_meu(self):
        p, escopo, pagas = ler_nova("iphone 15 4.500,90 12x dia 20 pagas 3 meu", HOJE)
        self.assertEqual((p.nome, p.valor, p.total, p.dia), ("iphone 15", D("4500.90"), 12, 20))
        self.assertEqual(p.primeiro_vencimento, date(2026, 7, 20))  # 20/10 é a 4ª parcela
        self.assertEqual(p.pagas(HOJE), 3)  # a de 20/10 ainda vai vencer
        self.assertEqual((escopo, pagas), ("meu", 3))

    def test_nova_invalida(self):
        for texto in ("Geladeira 250", "250 10x", "Geladeira 10x", "TV 100 3x pagas 3", "TV 100 3x dia 40"):
            self.assertIsInstance(ler_nova(texto, HOJE), str, texto)

    def test_lista_mostra_so_o_que_falta(self):
        ativa = Parcelamento("Geladeira", D("250"), 10, date(2026, 8, 20), 20, "p1")
        acabou = Parcelamento("TV", D("100"), 3, date(2026, 5, 10), 10, "p2")
        resposta = montar_lista([ativa, acabou], HOJE)
        self.assertEqual(len(resposta.lista), 1)
        self.assertEqual(resposta.lista[0][:2], ("par:p1", "Geladeira"))
        self.assertIn("3/10 de R$ 250,00 · próxima 20/10", resposta.lista[0][2])
        self.assertIn("Falta pagar R$ 2.000,00 no total; ainda vence R$ 250,00 este mês.", resposta.texto)

    def test_lista_tem_no_maximo_10_linhas(self):
        muitas = [Parcelamento(f"C{n}", D("10"), 5, date(2026, 9, 20), 20, f"p{n}") for n in range(12)]
        self.assertEqual(len(montar_lista(muitas, HOJE).lista), 10)

    def test_lista_vazia(self):
        self.assertIn("não tem parcelas", montar_lista([], HOJE))


@patch("app.comandos.parcelas.financas.hoje", return_value=HOJE)
@patch("app.comandos.parcelas.conta_do_usuario", return_value=("u1", "c1"))
class TestParcelasConversa(unittest.TestCase):
    @patch("app.comandos.parcelas.salvar_estado")
    def test_cadastro_pede_confirmacao(self, salvar, _conta, _hoje):
        resposta = comando_parcelas(USUARIO, "nova Geladeira 250 10x")
        self.assertIsInstance(resposta, Resposta)
        self.assertEqual(resposta.botoes, ("Sim", "Não"))
        self.assertIn("10x de R$ 250,00", resposta.texto)
        self.assertEqual(salvar.call_args.args[2]["primeiro"], "2026-11-16")

    @patch("app.comandos.parcelas._gravar")
    @patch("app.comandos.parcelas.limpar_estado")
    def test_sim_grava(self, _limpar, gravar, _conta, _hoje):
        dados = {"nome": "Geladeira", "valor": "250.00", "total": 10,
                 "primeiro": "2026-11-16", "dia": 16, "escopo": "conjunto"}
        resposta = continuar_parcela(USUARIO, dados, "Sim")
        gravar.assert_called_once()
        self.assertIn("previsão", resposta)

    @patch("app.comandos.parcelas._gravar")
    @patch("app.comandos.parcelas.limpar_estado")
    def test_nao_nao_grava(self, _limpar, gravar, _conta, _hoje):
        continuar_parcela(USUARIO, {}, "Não")
        gravar.assert_not_called()

    @patch("app.comandos.parcelas.listar_parcelas", return_value=[])
    def test_sem_argumentos_lista(self, _listar, _conta, _hoje):
        self.assertIn("não tem parcelas", comando_parcelas(USUARIO, ""))


VIAGEM = Objetivo("g1", "Viagem", D("5000"), date(2026, 12, 31), D("0"))


@patch("app.comandos.objetivos.financas.hoje", return_value=HOJE)
@patch("app.comandos.objetivos.conta_do_usuario", return_value=("u1", "c1"))
class TestObjetivosConversa(unittest.TestCase):
    @patch("app.comandos.objetivos.salvar_estado")
    @patch("app.comandos.objetivos.listar_objetivos", return_value=[])
    def test_criar_pede_confirmacao(self, _lista, salvar, _conta, _hoje):
        resposta = comando_objetivos(USUARIO, "novo Viagem 5000 12/2026")
        self.assertEqual(resposta.botoes, ("Sim", "Não"))
        self.assertEqual(salvar.call_args.args[2]["prazo"], "2026-12-31")

    @patch("app.comandos.objetivos._criar")
    @patch("app.comandos.objetivos.limpar_estado")
    def test_sim_cria(self, _limpar, criar, _conta, _hoje):
        dados = {"acao": "criar", "nome": "Viagem", "meta": "5000.00", "prazo": "2026-12-31"}
        resposta = continuar_objetivo(USUARIO, dados, "Sim")
        criar.assert_called_once()
        self.assertIn("guarde R$ 1.666,67 por mês", resposta)

    @patch("app.comandos.objetivos.salvar_estado")
    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM])
    def test_frase_de_aporte_pede_confirmacao(self, _lista, salvar, _conta, _hoje):
        resposta = frase_de_aporte(USUARIO, "guardei 200 viagem")
        self.assertEqual(resposta.texto, "Guardar R$ 200,00 em Viagem?")
        self.assertEqual(salvar.call_args.args[2]["objetivo"], "g1")

    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM])
    def test_aporte_em_objetivo_que_nao_existe(self, _lista, _conta, _hoje):
        self.assertIn("Em qual objetivo?", frase_de_aporte(USUARIO, "guardei 200 casa"))

    def test_frase_que_nao_e_de_poupanca(self, _conta, _hoje):
        self.assertIsNone(frase_de_aporte(USUARIO, "gastei 45 no mercado"))

    @patch("app.comandos.objetivos.listar_objetivos")
    @patch("app.comandos.objetivos._guardar")
    @patch("app.comandos.objetivos.limpar_estado")
    def test_sim_guarda_e_mostra_quanto_falta(self, _limpar, guardar, listar, _conta, _hoje):
        listar.return_value = [Objetivo("g1", "Viagem", D("5000"), date(2026, 12, 31), D("200"))]
        dados = {"acao": "aporte", "objetivo": "g1", "nome": "Viagem", "valor": "200.00"}
        resposta = continuar_objetivo(USUARIO, dados, "Sim")
        guardar.assert_called_once()
        self.assertIn("Guardado: R$ 200,00.", resposta)
        self.assertIn("Faltam R$ 4.800,00", resposta)


CARRO = Objetivo("g2", "Carro", D("9000"), date(2027, 6, 30), D("0"))
VIAGEM_COM_SALDO = Objetivo("g1", "Viagem", D("5000"), date(2026, 12, 31), D("800"))


@patch("app.comandos.objetivos.financas.hoje", return_value=HOJE)
@patch("app.comandos.objetivos.conta_do_usuario", return_value=("u1", "c1"))
@patch("app.comandos.objetivos.salvar_estado")
@patch("app.comandos.objetivos.limpar_estado")
class TestObjetivosGerir(unittest.TestCase):
    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM, CARRO])
    def test_lista_interativa_e_detalhes(self, _lista, _limpar, salvar, _conta, _hoje):
        resposta = comando_objetivos(USUARIO, "")
        self.assertEqual([l[0] for l in resposta.lista], ["obj:g1", "obj:g2"])
        self.assertEqual(salvar.call_args.args[1:], ("objetivo_gerir", {"etapa": "lista"}))
        detalhes = continuar_gerir(USUARIO, {"etapa": "lista"}, "obj:g2")
        self.assertEqual(detalhes.botoes, ("Editar", "Excluir"))
        self.assertIn("Carro", detalhes.texto)

    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM])
    def test_texto_fora_da_lista_e_ignorado(self, _lista, limpar, _salvar, _conta, _hoje):
        self.assertIsNone(continuar_gerir(USUARIO, {"etapa": "lista"}, "gastei 10 pão"))
        limpar.assert_called_once()

    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM])
    def test_editar_pelos_botoes(self, _lista, _limpar, salvar, _conta, _hoje):
        campos = continuar_gerir(USUARIO, {"etapa": "item", "id": "g1"}, "Editar")
        self.assertEqual(campos.botoes, ("Nome", "Valor", "Prazo"))
        pedido = continuar_gerir(USUARIO, {"etapa": "campo", "id": "g1"}, "Valor")
        self.assertIn("novo valor", pedido)
        self.assertEqual(salvar.call_args.args[2], {"etapa": "novo", "id": "g1", "campo": "valor"})

    @patch("app.comandos.objetivos.atualizar_objetivo")
    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM])
    def test_novo_valor_digitado(self, _lista, atualizar, _limpar, _salvar, _conta, _hoje):
        dados = {"etapa": "novo", "id": "g1", "campo": "valor"}
        self.assertIn("maior que zero", continuar_gerir(USUARIO, dados, "abc"))
        atualizar.assert_not_called()
        resposta = continuar_gerir(USUARIO, dados, "4.000")
        atualizar.assert_called_once_with("c1", "g1", "valor", D("4000.00"))
        self.assertTrue(resposta.startswith("Atualizado!"))

    @patch("app.comandos.objetivos.atualizar_objetivo")
    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM, CARRO])
    def test_comando_de_texto_edita_direto(self, _lista, atualizar, _limpar, _salvar, _conta, _hoje):
        comando_objetivos(USUARIO, "editar viagem valor 4000")
        atualizar.assert_called_once_with("c1", "g1", "valor", D("4000.00"))
        atualizar.reset_mock()
        comando_objetivos(USUARIO, "editar carro prazo 12/2027")
        atualizar.assert_called_once_with("c1", "g2", "prazo", date(2027, 12, 31))
        atualizar.reset_mock()
        self.assertIn("já tem", comando_objetivos(USUARIO, "editar carro nome viagem"))
        atualizar.assert_not_called()

    @patch("app.comandos.objetivos.excluir_objetivo")
    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM, CARRO])
    def test_excluir_sem_saldo_pede_sim_ou_nao(self, _lista, excluir, _limpar, salvar, _conta, _hoje):
        resposta = comando_objetivos(USUARIO, "excluir carro")
        self.assertEqual(resposta.botoes, ("Sim", "Não"))
        excluir.assert_not_called()
        dados = {"etapa": "excluir", "id": "g2"}
        continuar_gerir(USUARIO, dados, "Não")
        excluir.assert_not_called()
        continuar_gerir(USUARIO, dados, "Sim")
        excluir.assert_called_once_with("c1", "g2")

    @patch("app.comandos.objetivos.excluir_objetivo")
    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM_COM_SALDO, CARRO])
    def test_excluir_com_saldo_pergunta_o_que_fazer(self, _lista, excluir, _limpar, salvar, _conta, _hoje):
        resposta = comando_objetivos(USUARIO, "excluir viagem")
        self.assertEqual(resposta.botoes, ("Mover", "Só excluir", "Cancelar"))
        self.assertIn("R$ 800,00", resposta.texto)
        dados = {"etapa": "guardado", "id": "g1"}
        continuar_gerir(USUARIO, dados, "Cancelar")
        excluir.assert_not_called()
        destinos = continuar_gerir(USUARIO, dados, "Mover")
        self.assertEqual([l[0] for l in destinos.lista], ["obj:g2"])  # o próprio objetivo não aparece
        resposta = continuar_gerir(USUARIO, {"etapa": "destino", "id": "g1"}, "obj:g2")
        excluir.assert_called_once_with("c1", "g1", "g2")
        self.assertIn("movi R$ 800,00 para Carro", resposta)

    @patch("app.comandos.objetivos.excluir_objetivo")
    @patch("app.comandos.objetivos.listar_objetivos", return_value=[VIAGEM_COM_SALDO])
    def test_com_saldo_e_sem_outro_objetivo_nao_tem_mover(self, _lista, excluir, _limpar, _salvar, _conta, _hoje):
        resposta = comando_objetivos(USUARIO, "excluir viagem")
        self.assertEqual(resposta.botoes, ("Só excluir", "Cancelar"))
        self.assertIsNone(continuar_gerir(USUARIO, {"etapa": "guardado", "id": "g1"}, "Mover"))
        excluir.assert_not_called()  # digitar "mover" não pode apagar nada
        continuar_gerir(USUARIO, {"etapa": "guardado", "id": "g1"}, "Só excluir")
        excluir.assert_called_once_with("c1", "g1")


GELADEIRA = Parcelamento("Geladeira", D("250"), 10, date(2026, 8, 20), 20, "p1")  # 2 pagas em 16/10


@patch("app.comandos.parcelas.financas.hoje", return_value=HOJE)
@patch("app.comandos.parcelas.conta_do_usuario", return_value=("u1", "c1"))
@patch("app.comandos.parcelas.salvar_estado")
@patch("app.comandos.parcelas.limpar_estado")
@patch("app.comandos.parcelas.listar_parcelas", return_value=[GELADEIRA])
class TestParcelasGerir(unittest.TestCase):
    def test_lista_detalhes_e_botoes(self, _lista, _limpar, salvar, _conta, _hoje):
        resposta = comando_parcelas(USUARIO, "")
        self.assertEqual(resposta.lista[0][0], "par:p1")
        self.assertEqual(salvar.call_args.args[1:], ("parcela_gerir", {"etapa": "lista"}))
        detalhes = parcelas_gerir(USUARIO, {"etapa": "lista"}, "par:p1")
        self.assertEqual(detalhes.botoes, ("Editar", "Excluir"))
        self.assertIn("2 de 10 já pagas", detalhes.texto)

    def test_botoes_de_campo(self, _lista, _limpar, salvar, _conta, _hoje):
        campos = parcelas_gerir(USUARIO, {"etapa": "item", "id": "p1"}, "Editar")
        self.assertEqual(campos.botoes, ("Valor", "Nº de parcelas", "Pagas"))
        parcelas_gerir(USUARIO, {"etapa": "campo", "id": "p1"}, "Nº de parcelas")
        self.assertEqual(salvar.call_args.args[2]["campo"], "parcelas")

    @patch("app.comandos.parcelas.atualizar_parcela")
    def test_editar_valor_parcelas_e_pagas_por_texto(self, atualizar, _lista, _limpar, _salvar, _conta, _hoje):
        comando_parcelas(USUARIO, "editar geladeira valor 300")
        atualizar.assert_called_with("c1", GELADEIRA, "valor", D("300.00"), HOJE)
        comando_parcelas(USUARIO, "editar geladeira parcelas 12")
        atualizar.assert_called_with("c1", GELADEIRA, "parcelas", 12, HOJE)
        comando_parcelas(USUARIO, "editar geladeira pagas 4")
        atualizar.assert_called_with("c1", GELADEIRA, "pagas", 4, HOJE)

    @patch("app.comandos.parcelas.atualizar_parcela")
    def test_valores_invalidos_nao_gravam(self, atualizar, _lista, _limpar, _salvar, _conta, _hoje):
        self.assertIn("maior", comando_parcelas(USUARIO, "editar geladeira parcelas 2"))  # já pagou 2
        self.assertIn("0 a 9", comando_parcelas(USUARIO, "editar geladeira pagas 10"))
        self.assertIn("Mande só o número", comando_parcelas(USUARIO, "editar geladeira pagas abc"))
        atualizar.assert_not_called()

    @patch("app.comandos.parcelas.excluir_parcela")
    def test_excluir_pede_confirmacao(self, excluir, _lista, _limpar, _salvar, _conta, _hoje):
        resposta = comando_parcelas(USUARIO, "excluir geladeira")
        self.assertEqual(resposta.botoes, ("Sim", "Não"))
        parcelas_gerir(USUARIO, {"etapa": "excluir", "id": "p1"}, "Não")
        excluir.assert_not_called()
        parcelas_gerir(USUARIO, {"etapa": "excluir", "id": "p1"}, "Sim")
        excluir.assert_called_once_with("c1", "p1")


class TestAtualizarPagas(unittest.TestCase):
    """Mudar "pagas" muda o 1º vencimento; a previsão (que usa o vencimento) acompanha."""

    def test_pagas_reposiciona_o_primeiro_vencimento(self):
        capturado = {}

        class Conexao:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql, params): capturado.update(params)

        class Motor:
            def begin(self): return Conexao()

        with patch("app.comandos.parcelas.get_engine", return_value=Motor()):
            atualizar_parcela("c1", GELADEIRA, "pagas", 4, HOJE)
        self.assertEqual(capturado["valor"], date(2026, 6, 20))  # 20/10 passa a ser a 5ª parcela
        novo = Parcelamento("G", D("250"), 10, capturado["valor"], 20)
        self.assertEqual((novo.pagas(HOJE), novo.proximo_vencimento(HOJE)), (4, date(2026, 10, 20)))
        self.assertEqual(financas.valor_parcelas_a_vencer([novo], HOJE), D("250"))


class TestRoteamento(unittest.TestCase):
    def test_comandos_registrados(self):
        self.assertIn("objetivos", COMANDOS_COM_USUARIO)
        self.assertIn("parcelas", COMANDOS_COM_USUARIO)


if __name__ == "__main__":
    unittest.main()
