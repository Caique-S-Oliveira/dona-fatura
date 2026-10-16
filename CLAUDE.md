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
(Ao fim de cada etapa, acrescente uma linha: "Etapa N concluída — resumo curto".)
(Etapas 5 em diante seguem a nova ordem de dona-fatura-ajustes-pos-pesquisa.md.)
