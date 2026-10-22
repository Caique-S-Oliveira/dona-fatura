"""Etapa 14: alertas (/cron) e alerta de gasto muito acima do normal.

Os testes de banco rodam SQL de verdade num SQLite em memória (nunca no banco real) e trocam o
envio do WhatsApp por uma lista, então nada é enviado de verdade.
"""
import os
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from app import alertas
from app.financas import BRASIL, Parcelamento
from tests.test_casal import ANA, BancoDeTeste

D = Decimal
# Segunda-feira, 10h05 em Brasília. A semana passada foi de 12 a 18/10.
AGORA = datetime(2026, 10, 19, 10, 5, tzinfo=BRASIL)

EXTRA = """
CREATE TABLE sent_alerts (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    account_id TEXT NOT NULL, user_id TEXT NOT NULL, alert_type TEXT NOT NULL,
    deduplication_key TEXT NOT NULL, period_start TEXT, period_end TEXT, whatsapp_message_id TEXT,
    sent_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    UNIQUE (account_id, user_id, deduplication_key));
CREATE TABLE reminder_log (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))), user_id TEXT NOT NULL, day TEXT NOT NULL,
    stage_days INTEGER, result TEXT NOT NULL, reason TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    UNIQUE (user_id, day));
CREATE TABLE processed_messages (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    whatsapp_message_id TEXT, sender_phone_number TEXT NOT NULL, received_at TEXT);
"""


class TestRegras(unittest.TestCase):
    def test_semana_comeca_na_segunda(self):
        self.assertEqual(alertas.inicio_da_semana(datetime(2026, 10, 18, 23, 0, tzinfo=BRASIL)),
                         datetime(2026, 10, 12, tzinfo=BRASIL))
        self.assertEqual(alertas.inicio_da_semana(AGORA), datetime(2026, 10, 19, tzinfo=BRASIL))

    def test_janela_de_24h(self):
        self.assertTrue(alertas.dentro_da_janela(AGORA - timedelta(hours=10), AGORA))
        self.assertFalse(alertas.dentro_da_janela(AGORA - timedelta(hours=24), AGORA))
        self.assertFalse(alertas.dentro_da_janela(AGORA - timedelta(hours=23, minutes=55), AGORA))
        self.assertFalse(alertas.dentro_da_janela(None, AGORA))

    def test_semana_passada(self):
        self.assertEqual(
            alertas.periodos_da_semana_passada(date(2026, 10, 21)),
            (date(2026, 10, 12), date(2026, 10, 18), date(2026, 10, 5), date(2026, 10, 11)),
        )

    def test_mes_passado_so_na_primeira_segunda(self):
        self.assertTrue(alertas.primeira_segunda_do_mes(date(2026, 10, 5)))
        self.assertFalse(alertas.primeira_segunda_do_mes(date(2026, 10, 12)))

    def test_metas_80_e_100(self):
        metas = {"Variável": D("1000"), "Fixo": D("1000"), "Assinatura": D("100"), "Investimento": D("500")}
        real = {"Variável": D("850"), "Fixo": D("1000"), "Assinatura": D("50"), "Investimento": D("600")}
        linhas = alertas.linhas_de_metas(metas, real)
        self.assertEqual(len(linhas), 2)  # Assinatura (50%) e Investimento (mínimo) ficam de fora
        self.assertIn("85%", linhas[0])
        self.assertIn("passou da meta", linhas[1])

    def test_vencimentos_de_amanha(self):
        dia = date(2026, 10, 19)
        contas = [("Netflix", D("39.90"), date(2026, 10, 20)), ("Aluguel", D("1500"), date(2026, 10, 25))]
        parcelas = [Parcelamento("Geladeira", D("200"), 10, date(2026, 8, 20), 20)]  # 3ª parcela vence dia 20
        achados = alertas.vencimentos_de_amanha(contas, parcelas, dia)
        self.assertEqual([a.nome for a in achados], ["Netflix", "Geladeira"])
        self.assertEqual(achados[1].detalhe, "parcela 3/10")

    def test_gasto_muito_acima(self):
        normais = [D("50")] * 5
        self.assertEqual(alertas.gasto_muito_acima(D("200"), normais), D("50"))
        self.assertIsNone(alertas.gasto_muito_acima(D("140"), normais))  # menos de 3x
        self.assertIsNone(alertas.gasto_muito_acima(D("200"), normais[:4]))  # pouco histórico
        self.assertIsNone(alertas.gasto_muito_acima(D("90"), [D("10")] * 5))  # abaixo de R$ 100

    def test_ia_com_numero_novo_vale_o_texto_pronto(self):
        with patch.object(alertas.ia, "chamar_ia", return_value="Você gastou R$ 999,00!"):
            self.assertEqual(alertas.texto_do_alerta("Saldo R$ 10,00."), "Saldo R$ 10,00.")
        with patch.object(alertas.ia, "chamar_ia", return_value="Atenção: saldo de R$ 10,00."):
            self.assertEqual(alertas.texto_do_alerta("Saldo R$ 10,00."), "Atenção: saldo de R$ 10,00.")

    def test_modelos_desligados_por_padrao(self):
        with patch.dict(os.environ, {"MODELOS_ATIVOS": "0"}):
            self.assertFalse(alertas.modelos_ativos())
        with patch.dict(os.environ, {"MODELOS_ATIVOS": "1"}):
            self.assertTrue(alertas.modelos_ativos())


class BaseCron(BancoDeTeste):
    def setUp(self):
        super().setUp()
        with self.motor.begin() as conexao:
            for comando in EXTRA.split(";\n"):
                if comando.strip():
                    conexao.exec_driver_sql(comando)
        self.textos, self.modelos = [], []
        for nome, destino in (
            ("send_text", lambda para, corpo: self.textos.append((para, corpo)) or "wamid.1"),
            ("send_template", lambda para, nome_, params, botoes=(): self.modelos.append((para, nome_, params, botoes)) or "wamid.2"),
        ):
            patcher = patch(f"app.whatsapp.{nome}", destino)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(alertas.ia, "chamar_ia", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cadastrar(ANA, "Ana", 4500)
        self.sql("UPDATE users SET created_at = '2026-09-01 08:00:00'")

    def mensagem_da_ana(self, quando):
        self.sql("INSERT INTO processed_messages (sender_phone_number, received_at) VALUES (:t, :q)",
                 t=ANA, q=quando.isoformat())

    def movimento_na_semana_passada(self):
        usuario, conta = self.ids(ANA)
        for tipo, valor in (("income", 1000), ("expense", 100)):
            self.sql("INSERT INTO transactions (account_id, created_by_user_id, transaction_type, amount,"
                     " transaction_date, scope, created_at) VALUES (:c, :u, :t, :v, '2026-10-14', 'meu',"
                     " '2026-10-14 12:00:00')", c=conta, u=usuario, t=tipo, v=valor)

    def alertas_gravados(self):
        return [l[0] for l in self.sql("SELECT deduplication_key FROM sent_alerts ORDER BY sent_at, deduplication_key")]

    # os testes ficam em TestCron, abaixo


class TestCron(BaseCron):
    def test_so_age_as_10h(self):
        self.mensagem_da_ana(AGORA.replace(hour=15) - timedelta(hours=1))
        self.movimento_na_semana_passada()
        alertas.executar_alertas(agora=AGORA.replace(hour=15))
        self.assertEqual(self.textos, [])
        alertas.executar_alertas(forcar=True, agora=AGORA.replace(hour=15))
        self.assertEqual(len(self.textos), 1)

    def test_prioridade_e_sem_repeticao(self):
        self.mensagem_da_ana(AGORA - timedelta(hours=1))
        self.movimento_na_semana_passada()
        alertas.executar_alertas(agora=AGORA)
        self.assertEqual(len(self.textos), 1)
        self.assertIn("Resumo da semana passada", self.textos[0][1])
        self.assertIn("Entradas: R$ 1.000,00", self.textos[0][1])
        self.assertEqual(self.alertas_gravados(), ["resumo_semanal:2026-10-19"])
        alertas.executar_alertas(agora=AGORA)  # mesmo dia: o resumo não repete e não há mais nada
        self.assertEqual(len(self.textos), 1)
        self.assertEqual(self.modelos, [])

    def test_vencimento_amanha(self):
        usuario, conta = self.ids(ANA)
        self.mensagem_da_ana(AGORA - timedelta(hours=1))
        self.sql("INSERT INTO recurring_transactions (account_id, created_by_user_id, payee, amount,"
                 " next_due_date, scope) VALUES (:c, :u, 'Netflix', 40, '2026-10-20', 'conjunto')",
                 c=conta, u=usuario)
        alertas.executar_alertas(agora=AGORA)
        self.assertIn("Netflix", self.textos[0][1])
        self.assertIn("R$ 40,00", self.textos[0][1])

    def test_limite_de_3_por_semana(self):
        usuario, conta = self.ids(ANA)
        self.mensagem_da_ana(AGORA - timedelta(hours=1))
        self.movimento_na_semana_passada()
        for n in range(3):
            self.sql("INSERT INTO sent_alerts (account_id, user_id, alert_type, deduplication_key, sent_at)"
                     " VALUES (:c, :u, 'x', :k, '2026-10-19 12:00:00')", c=conta, u=usuario, k=f"k{n}")
        alertas.executar_alertas(agora=AGORA)
        self.assertEqual(self.textos, [])

    def test_fora_da_janela_pula_sem_marcar(self):
        self.mensagem_da_ana(AGORA - timedelta(hours=30))
        self.movimento_na_semana_passada()
        with patch.dict(os.environ, {"MODELOS_ATIVOS": "0"}):
            alertas.executar_alertas(agora=AGORA)
        self.assertEqual((self.textos, self.modelos, self.alertas_gravados()), ([], [], []))

    def test_fora_da_janela_usa_modelo_se_ligado(self):
        self.mensagem_da_ana(AGORA - timedelta(hours=30))
        self.movimento_na_semana_passada()
        with patch.dict(os.environ, {"MODELOS_ATIVOS": "1"}):
            alertas.executar_alertas(agora=AGORA)
        self.assertEqual(self.textos, [])
        para, nome, params, _ = self.modelos[0]
        self.assertEqual((para, nome), (ANA, "resumo_semanal"))
        self.assertEqual(params[:4], ["12 a 18/10", "R$ 1.000,00", "R$ 100,00", "R$ 900,00"])
        self.assertEqual(self.alertas_gravados(), ["resumo_semanal:2026-10-19"])

    def test_envio_com_erro_nao_marca(self):
        self.mensagem_da_ana(AGORA - timedelta(hours=1))
        self.movimento_na_semana_passada()
        with patch("app.whatsapp.send_text", side_effect=RuntimeError("fora do ar")):
            alertas.executar_alertas(agora=AGORA)
        self.assertEqual(self.alertas_gravados(), [])

    def test_usuario_bloqueado_nao_recebe(self):
        self.mensagem_da_ana(AGORA - timedelta(hours=1))
        self.movimento_na_semana_passada()
        self.sql("UPDATE users SET access_status = 'bloqueado'")
        alertas.executar_alertas(agora=AGORA)
        self.assertEqual(self.textos, [])

    def test_gasto_muito_acima_vai_para_a_fila_e_conta_no_limite(self):
        usuario, conta = self.ids(ANA)
        cat = self.categoria(ANA, "Restaurante", "Variável")
        for _ in range(5):
            self.registrar(ANA, 50, "meu", categoria=cat)
        self.registrar(ANA, 400, "meu", categoria=cat)  # o gasto que acabou de ser confirmado
        alertas.abrir_fila()
        alertas.preparar_alerta_gasto(ANA, conta, usuario, {"valor": "400"}, cat)
        alertas.enviar_alertas_de_gasto()
        self.assertEqual(len(self.textos), 1)
        self.assertIn("R$ 400,00", self.textos[0][1])
        self.assertIn("R$ 50,00", self.textos[0][1])
        self.assertTrue(self.alertas_gravados()[0].startswith("gasto_alto:"))

    def test_gasto_normal_nao_alerta_e_sem_fila_nao_faz_nada(self):
        usuario, conta = self.ids(ANA)
        cat = self.categoria(ANA, "Restaurante", "Variável")
        for _ in range(6):
            self.registrar(ANA, 50, "meu", categoria=cat)
        alertas.preparar_alerta_gasto(ANA, conta, usuario, {"valor": "50"}, cat)  # sem fila aberta
        alertas.abrir_fila()
        alertas.preparar_alerta_gasto(ANA, conta, usuario, {"valor": "50"}, cat)
        alertas.enviar_alertas_de_gasto()
        self.assertEqual(self.textos, [])


class TestLembreteDeInatividade(BaseCron):
    """Lembrete por modelo: aos 3 e aos 7 dias sem mensagem do usuário."""

    def setUp(self):
        super().setUp()
        patcher = patch.dict(os.environ, {"MODELOS_ATIVOS": "1", "INATIVIDADE_DIAS": "3", "MODELO_LEMBRETE": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def parada_ha(self, dias):
        self.mensagem_da_ana(AGORA - timedelta(days=dias, hours=1))

    def log(self):
        return [tuple(l) for l in self.sql("SELECT result, reason FROM reminder_log ORDER BY created_at")]

    def test_recente_nao_recebe_nem_gera_log(self):
        self.parada_ha(2)
        alertas.executar_alertas(agora=AGORA)
        self.assertEqual((self.modelos, self.log()), ([], []))

    def test_3_dias_envia_modelo_com_nome_data_e_botoes(self):
        self.parada_ha(3)
        alertas.executar_alertas(agora=AGORA)
        para, nome, params, botoes = self.modelos[0]
        self.assertEqual((para, nome), (ANA, "lembrete_registro"))
        self.assertEqual(params, ["Ana", "01/09"])  # sem registros: vale o dia do cadastro
        self.assertEqual(botoes, ("lembrete_registrar", "lembrete_parar"))
        self.assertEqual(self.log()[0][0], "enviado")
        self.assertEqual(self.textos, [])

    def test_um_aos_3_dias_outro_aos_7_e_depois_para(self):
        self.parada_ha(3)
        alertas.executar_alertas(agora=AGORA)
        alertas.executar_alertas(agora=AGORA)  # mesmo dia: não repete
        self.assertEqual(len(self.modelos), 1)
        alertas.executar_alertas(agora=AGORA + timedelta(days=2))  # 5 dias parada: nada novo
        self.assertEqual(len(self.modelos), 1)
        depois = AGORA + timedelta(days=4)  # 7 dias parada: o segundo
        alertas.executar_alertas(agora=depois)
        self.assertEqual(len(self.modelos), 2)
        alertas.executar_alertas(agora=depois + timedelta(days=5))  # 12 dias: para
        self.assertEqual(len(self.modelos), 2)

    def test_volta_e_para_de_novo_recomeca(self):
        self.parada_ha(3)
        alertas.executar_alertas(agora=AGORA)
        depois = AGORA + timedelta(days=10)
        self.mensagem_da_ana(depois - timedelta(days=3, hours=1))  # voltou e parou outra vez
        alertas.executar_alertas(agora=depois)
        self.assertEqual(len(self.modelos), 2)

    def test_modelos_desligados_pula_e_registra_o_motivo(self):
        self.parada_ha(3)
        with patch.dict(os.environ, {"MODELOS_ATIVOS": "0"}):
            alertas.executar_alertas(agora=AGORA)
        self.assertEqual(self.modelos, [])
        self.assertEqual(self.alertas_gravados(), [])
        self.assertIn("modelos desligados", self.log()[0][1])

    def test_lembretes_desligados_pelo_usuario(self):
        self.parada_ha(3)
        self.sql("UPDATE users SET lembretes_ativos = 0")
        alertas.executar_alertas(agora=AGORA)
        self.assertEqual(self.modelos, [])
        self.assertIn("desligados pelo usuário", self.log()[0][1])

    def test_limite_semanal_vale_para_o_lembrete(self):
        usuario, conta = self.ids(ANA)
        self.parada_ha(3)
        for n in range(3):
            self.sql("INSERT INTO sent_alerts (account_id, user_id, alert_type, deduplication_key, sent_at)"
                     " VALUES (:c, :u, 'x', :k, '2026-10-19 08:00:00')", c=conta, u=usuario, k=f"k{n}")
        alertas.executar_alertas(agora=AGORA)
        self.assertEqual(self.modelos, [])
        self.assertIn("limite", self.log()[0][1])

    def test_api_recusa_nao_tenta_de_novo_no_dia(self):
        self.parada_ha(3)
        tentativas = []

        def recusa(*args, **kwargs):
            tentativas.append(1)
            raise RuntimeError("template paused")

        with patch("app.whatsapp.send_template", recusa):
            alertas.executar_alertas(agora=AGORA)
            alertas.executar_alertas(agora=AGORA)
        self.assertEqual(len(tentativas), 1)
        self.assertEqual(self.alertas_gravados(), [])
        resultado, motivo = self.log()[0]
        self.assertEqual(resultado, "erro")
        self.assertIn("template paused", motivo)
        alertas.executar_alertas(agora=AGORA + timedelta(days=1))  # no dia seguinte tenta de novo
        self.assertEqual(len(self.modelos), 1)

    def test_nome_do_modelo_vem_do_env(self):
        self.parada_ha(3)
        with patch.dict(os.environ, {"MODELO_LEMBRETE": "outro_nome"}):
            alertas.executar_alertas(agora=AGORA)
        self.assertEqual(self.modelos[0][1], "outro_nome")


class TestBotoesDoLembrete(BaseCron):
    def test_parar_grava_preferencia_e_lembretes_religa(self):
        from app.comandos import lembretes, processar_mensagem

        texto, botoes = lembretes.tratar_botao(ANA, "lembrete_parar", "Parar lembretes")
        self.assertEqual(botoes, [])
        self.assertFalse(lembretes.lembretes_ligados(self.ids(ANA)[0]))
        self.assertIn("ligados", processar_mensagem(ANA, "/lembretes"))
        self.assertTrue(lembretes.lembretes_ligados(self.ids(ANA)[0]))

    def test_registrar_agora_ensina_e_oferece_botoes(self):
        from app.comandos import lembretes

        texto, botoes = lembretes.tratar_botao(ANA, None, "Registrar agora")  # sem payload: vale o título
        self.assertIn("/gasto", texto)
        self.assertIn("comprovante", texto)
        self.assertTrue(botoes)

    def test_outros_botoes_nao_sao_do_lembrete(self):
        from app.comandos import lembretes

        self.assertIsNone(lembretes.tratar_botao(ANA, "sim", "Sim"))
        self.assertIsNone(lembretes.tratar_botao(ANA, "lembrete_resumo", "Ver meu resumo"))


if __name__ == "__main__":
    unittest.main()
