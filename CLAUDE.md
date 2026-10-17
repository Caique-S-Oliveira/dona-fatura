# Dona Fatura — assistente financeiro no WhatsApp

## Sobre o dono do projeto
- Iniciante: sei um pouco de Python. Uso Windows e VS Code.
- Ao terminar, explique em português simples o que fez e como testar, em no máximo 10 linhas.
- Faça só o que a etapa pedir. Não adiante etapas futuras.
- Pergunte antes de instalar biblioteca nova ou mexer em algo fora da etapa.
- Prefira alterar trechos a reescrever arquivos inteiros.
- Nunca leia, mostre ou faça commit do arquivo .env.

## O produto
Bot de WhatsApp que registra entradas (salário) e saídas (comprovantes de pagamento/Pix e texto),
compara com metas definidas pelo usuário, prevê o fim do mês e diz o que corrigir.
Uso pessoal e de amigos. Português do Brasil, R$ 1.234,56, datas dd/mm/aaaa,
fuso America/Sao_Paulo.
Personagem: "Dona Fatura": direta e objetiva; firme ao avisar de gasto fora do plano, sem
esconder o problema; um toque de simpatia, sem sermão. Mensagens curtas (até ~5 linhas).

## Tecnologia
- Python 3.11+, FastAPI + uvicorn (webhook)
- PostgreSQL no Supabase via SQLAlchemy + psycopg (DATABASE_URL do Session pooler)
- WhatsApp Cloud API (Meta) via httpx
- API do Claude (SDK anthropic); modelo na variável ANTHROPIC_MODEL (padrão claude-haiku-5-5)
- matplotlib para gráficos em PNG
- Hospedagem: Render grátis (dorme após 15 min sem uso). Alertas: rota /cron protegida
  por CRON_SECRET, chamada pelo cron-job.org.
- Configuração só por variáveis de ambiente (.env local; .env.example sem valores).

## Modos de uso
- Individual: 1 número, 1 conta.
- Casal: 2 números na mesma conta (/casal gera código; o parceiro manda /entrar CÓDIGO).
- Grupo: /grupo — o bot cria um grupo pela Groups API da Cloud API e envia o link de
  convite; o casal manda e recebe tudo no grupo. Usa a mesma conta do casal.
- Privacidade: toda transação tem escopo "conjunto" (padrão) ou "meu". Ao entrar no casal,
  perguntar UMA vez: "tudo junto" (padrão) ou "com gastos pessoais". Em "tudo junto" não
  perguntar [Meu] [Conjunto] a cada registro; o sufixo "meu" (ex.: /gasto 30 padaria meu)
  ainda marca um gasto como privado. Em "com gastos pessoais", perguntar [Meu] [Conjunto].
  Gastos "meu" só o dono vê em detalhe; o parceiro vê no máximo o total somado. No grupo,
  nunca detalhar gastos "meu".
- Renda de cada um visível ao parceiro (valor completo).
- Metas do casal: conjuntas e também individuais.

## Categorias e metas
- Tipos: Fixo, Variável, Assinatura, Investimento, Reserva de emergência.
- Subcategorias padrão: Moradia, Mercado, Transporte, Saúde, Lazer, Restaurante, Pets,
  Parcelas/dívidas, Viagens, Educação, Outros; o usuário pode criar outras.
- No /inicio o formato padrão das metas é R$ por tipo; % da renda é opção, com atalho
  opcional "usar 50/30/20". Editáveis em /metas.
- Objetivos de poupança (/objetivos): nome, valor e prazo; o bot diz quanto falta e quanto
  guardar por mês. Parcelas (/parcelas) entram nos fixos a vencer da previsão.

## Fluxos principais
- Registro por texto é prioridade: "/gasto 45,90 mercado" e frases simples como
  "gastei 45 no mercado" (extração por regras primeiro, IA só se não entender),
  com sugestão de categoria e botões [Sim] [Corrigir].
- Comprovante (foto/PDF): IA extrai valor, data e favorecido e sugere a categoria
  (regras aprendidas são consultadas antes da IA) -> botões [Sim] [Corrigir].
- Holerite é opcional: o bot oferece /entrada VALOR como alternativa e nunca exige a foto.
  Se enviado (foto/PDF): IA extrai valor líquido e data -> botões [Sim] [Corrigir];
  Corrigir pede o valor por texto. Nada é salvo sem confirmação.
- Aprendizado: ao corrigir a categoria, salvar a regra favorecido -> categoria da conta.
- Recorrentes: mesmo favorecido com valor parecido em 2+ meses -> perguntar se é recorrente.
- Previsão do mês: entradas - saídas - fixos/assinaturas/parcelas que ainda vencem
  - (média diária de variáveis dos últimos 3 meses x dias restantes).
- Diagnóstico: real x meta por tipo; diz o que está fora e quanto ajustar por semana
  até o fim do mês para bater as metas.
- /resumo mostra também a variação em relação ao mês anterior. /resumo semana mostra a semana.
- Privacidade: depois de ler foto ou PDF, descartar o arquivo e guardar só valor, data,
  favorecido e categoria. /privacidade explica o que é guardado e quem tem acesso (diga a
  verdade, inclusive que o administrador do banco consegue ver os dados). /apagar_meus_dados
  apaga tudo, com confirmação. Só afirmar "criptografia" depois de conferir na documentação
  do Supabase e do Render.
- A IA não calcula: todos os números vêm do Python; a IA só escreve o texto final.

## Comandos
/inicio /metas /resumo /gasto VALOR DESCRIÇÃO /entrada VALOR DESCRIÇÃO /categorias /fixos
/previsao /diagnostico /objetivos /parcelas /desfazer /privacidade /apagar_meus_dados /ajuda
/grafico previsao   (outros gráficos só se o piloto pedir)
/casal /entrar CÓDIGO /grupo   (no casal: sufixo "meu" ou "casal", ex.: /resumo casal)
Mensagem que não é comando -> IA identifica qual comando o usuário quer (resposta curta em
JSON). Nunca chamar a IA para um comando já reconhecido.

## Regras do WhatsApp
- Validar a assinatura X-Hub-Signature-256 com WHATSAPP_APP_SECRET.
- Responder 200 rápido ao webhook e ignorar mensagens repetidas (guardar o id da mensagem).
- Confirmações usam botões de resposta rápida (no máximo 3).
- Gráficos: gerar PNG, fazer upload na rota /media da API e enviar pelo id da mídia.
- Fora da janela de 24h só é possível enviar modelos (templates) aprovados; alertas usam modelos.

## Alertas
- No máximo 3 mensagens automáticas por semana por usuário; padrão às 10h (America/Sao_Paulo).
- Ordem de prioridade: (1) resumo semanal, (2) conta, assinatura ou parcela vencendo
  amanhã, (3) gasto muito acima do normal, (4) lembrete após 4 dias sem registros (ajustável).
- Meta em 80% e 100% e resumo do mês anterior vão dentro do resumo semanal, sem modelo próprio.
- Usar o mínimo de modelos (templates) aprovados, porque são cobrados.

## Custos (prioridade: gastar o mínimo)
- IA só para documentos e frases livres, com max_tokens baixo.
- Não usar nenhum serviço pago sem eu pedir.

## Estrutura
app/main.py, app/whatsapp.py, app/db.py, app/models.py, app/ia.py, app/financas.py,
app/graficos.py, app/comandos/, sql/schema.sql, tests/

## Progresso
## Progresso
(Ao fim de cada etapa, acrescente uma linha: "Etapa N concluída — resumo curto".)
Etapa 1 concluída — estrutura inicial, endpoint de saúde e Git local criados.
Etapa 2 concluída — esquema PostgreSQL e teste de conexão pelo DATABASE_URL criados.
Etapa 3 concluída — webhook do WhatsApp (verificação, assinatura, anti-repetição, resposta "Oi, eu sou a Dona Fatura!").
Etapa 4 concluída — roteador de comandos em app/comandos/, cadastro automático, /ajuda e "Ainda estou aprendendo isso".
Etapa 4 (complemento) concluída — controle de acesso: status pendente/ativo/bloqueado, /convite, /liberar e /bloquear (admin), sql/alter_acesso.sql.
(Ao fim de cada etapa, acrescente uma linha: "Etapa N concluída — resumo curto".)
(Etapas 5 em diante seguem a nova ordem de dona-fatura-ajustes-pos-pesquisa.md.)
Etapa 5 concluída — /inicio passo a passo (nome, renda, metas em R$, % ou 50/30/20) com aviso de privacidade, /metas para ver e alterar, estado da conversa no banco, sql/alter_inicio.sql.
Etapa 6 concluída — /gasto e frase "gastei 45 no mercado" (regras, IA só se não entender), sugestão de categoria (regras aprendidas > nome > palavras > IA) com botões [Sim] [Corrigir] e aprendizado, /categorias (listar/criar), /desfazer com confirmação, app/ia.py.
Etapa 6 (complemento) concluída — mensagens interativas: Corrigir -> [Valor] [Categoria]; lista de categorias (8 mais usadas + "Outras…" + "➕ Nova categoria"); /categorias abre a lista; nova categoria com nome por texto e tipo por botões.
Etapa 7 concluída — comprovante (foto/PDF): baixa da Meta, IA extrai valor/data/favorecido, sugere categoria (regras aprendidas > IA), [Sim] [Corrigir] reaproveitando o fluxo do /gasto, arquivo descartado (app/comandos/comprovante.py).
Etapa 8 concluída — /entrada VALOR DESCRIÇÃO com confirmação; /entrada sozinho oferece o texto e aceita holerite opcional (foto/PDF -> IA lê valor líquido e data -> [Sim] [Corrigir]; arquivo descartado; se não ler, pede o valor por texto) (app/comandos/entrada.py).
Etapa 9 concluída — /resumo (mês, com variação x mês passado) e /resumo semana (app/financas.py), frases livres identificadas pela IA (só quando nenhuma regra entende), /privacidade e /apagar_meus_dados com botões [Apagar tudo] [Cancelar].
Etapa 10 concluída — previsão do mês (app/financas.py), /previsao em texto, /grafico previsao (deveria estar x está x projeção, app/graficos.py, envio de imagem pela /media), scripts/dados_teste.py e scripts/apagar_dados_teste.py.
Etapa 11 concluída — detecção de recorrentes (mesmo favorecido, valor parecido em 2+ meses -> [Sim] [Não]; app/comandos/recorrentes.py) e /fixos (pagos x a vencer x atrasados; app/comandos/fixos.py).
Etapa 12 concluída — /diagnostico: real x meta por tipo em Python (app/financas.py), mostra só o que está fora e quanto cortar/guardar por semana; a IA só reescreve o texto com os números prontos (se inventar número ou falhar, vale o texto pronto; app/comandos/diagnostico.py).
Etapa 13 concluída — /objetivos (novo NOME VALOR PRAZO, "guardei 200 viagem" com confirmação, quanto falta e quanto guardar por mês) e /parcelas (nova NOME VALOR Nx; lista o que falta; parcelas que ainda vencem entram no a vencer da previsão), sql/alter_objetivos_parcelas.sql.
Etapa 13 (complemento) concluída — editar e excluir objetivos e parcelas: /objetivos e /parcelas abrem lista interativa -> detalhes [Editar] [Excluir]; edição por botões + texto (ou /objetivos editar viagem valor 4000); excluir objetivo com saldo pergunta [Mover] [Só excluir] [Cancelar]. Sem SQL novo.
Etapa 15 concluída — modo casal: /casal gera código (48h, uso único), /entrar CÓDIGO junta o parceiro na conta e pergunta UMA vez "tudo junto" ou "com gastos pessoais" (só no 2º o gasto e o comprovante perguntam [Meu] [Conjunto]; sufixo "meu" sempre vale); renda de cada um visível em /metas; metas do casal e individuais (/metas TIPO VALOR meu; /inicio no casal grava metas individuais; /diagnostico mostra as duas); parceiro vê só o total dos gastos "meu" do outro; testes em tests/test_casal.py (SQLite em memória), sql/alter_casal.sql.
Etapa 15 concluída — /sair_casal: confirma com [Sim] [Não], troca a conta do casal por duas contas individuais (cada um fica com seus "meu" e metas individuais; os dois ganham cópia do histórico conjunto, categorias, regras, metas do casal, parcelas, contas fixas e objetivos), avisa o parceiro (se fora da janela de 24h, o aviso espera a próxima mensagem dele), tudo numa transação; sql/alter_sair_casal.sql (tabela pending_notices).
Etapa 14 concluída — rota /cron (header X-Cron-Secret) com alertas sem repetir, máx. 3/semana por usuário: resumo semanal (com metas 80%/100% e mês anterior), vencimento amanhã, lembrete após 4 dias; texto só na janela de 24h, modelos prontos mas desligados (MODELOS_ATIVOS=0); alerta de gasto muito acima do normal logo após a confirmação (app/alertas.py, docs/modelos_whatsapp.md). Sem SQL novo.
