# Relatório de segurança e LGPD — Dona Fatura

Data: 23/10/2026 · Branch: `security-audit-2026-10` · Fases 1 a 5 concluídas.
Não sou advogado: itens marcados **[JURÍDICO]** precisam de revisão de quem é.

## 1. Resumo executivo

- **Projetos auditados: 1** (Dona Fatura: API FastAPI + bot de WhatsApp + landing estática). Não há outros diretórios com código, Dockerfile ou CI.
- **Achados de segurança (Fase 2): 13** — 1 alta (a confirmar no painel), 2 médias, 10 baixas.
  - Corrigidos no código: **11** (#2 a #4, #6 a #8, #10 a #13 e #5 em parte, ver tabela).
  - Aceito com justificativa: **1** (#9, limite por IP em memória).
  - Pendentes (dependem do painel do Supabase): **1** (#1, RLS) + confirmação do #5.
- **Lacunas LGPD (Fase 3): 11** — corrigidas total ou parcialmente: L1 (parcial), L2, L3, L4, L5 (parcial), L7. Pendentes por decisão sua/jurídica: L1 (prazos de dados financeiros e leads), L6, L8, L9, L10, L11.
- **Verificação (Fase 5):** 384 testes passam; pip-audit sem vulnerabilidades; nenhum achado novo de SQL injection; nenhum segredo ou `.env` no histórico do Git (ver limitação sobre o gitleaks).

## 2. Verificação (Fase 5)

Saída bruta em `audit/raw/fase5/` (fora do Git).

| Ferramenta | Antes (Fase 1) | Agora | Conclusão |
|---|---|---|---|
| pytest | — | **384 passed** | Nada regrediu |
| pip-audit | 0 vulnerabilidades | 0 vulnerabilidades (com versões fixas) | Ok |
| bandit | 10× B608, 1× B311 | 14× B608, 1× B406, 1× B311 | Tudo falso positivo, ver abaixo |
| semgrep | 10× avoid-sqlalchemy-text | 10× avoid-sqlalchemy-text, 1× use-defused-xml | Idem |
| Segredos no histórico | arquivo vazio (dúvida se rodou) | gitleaks **não instalável aqui**; fiz busca por padrões (chaves `sk-ant-`, tokens Meta, URLs de banco com senha, chaves privadas, `SECRET/TOKEN=`) em todo o histórico: **nada encontrado**. Arquivos `.env*` no histórico: só `.env.example` | Ok, mas rode o gitleaks quando puder |

Novos achados das ferramentas, todos revisados à mão:
- **B608 em `app/retencao.py` (4×)**: a f-string só insere `DIAS_MENSAGENS`/`DIAS_LOGS`/`DIAS_AVISOS`, inteiros fixos do código. Nenhuma entrada do usuário. Falso positivo.
- **B608/semgrep nos mesmos pontos antigos** (`metas.py`, `objetivos.py`, `parcelas.py`, `sair_casal.py`, `financas.py`, `estado.py`, `acesso.py`): trechos fixos ou whitelist; valores do usuário vão por parâmetro `:x`. O aumento de 10 para 14 vem só do `retencao.py`. Falso positivo.
- **B406/use-defused-xml em `app/xlsx.py`**: usa só `xml.sax.saxutils.escape` para *gerar* o arquivo (exportação do `/meus_dados`); nenhum XML de terceiros é lido. Falso positivo. Observação: `escape` não troca aspas `"`; os nomes de aba são fixos no código, então não há risco hoje.
- **B311 em `scripts/dados_teste.py`**: `random` para dado de teste. Irrelevante.

## 3. Achados de segurança

| # | Sev. | Onde | Achado | Status | Commit |
|---|---|---|---|---|---|
| 1 | Alta (a confirmar) | `sql/*.sql` | Só `leads` tem RLS; as outras tabelas ficam no schema `public` do Supabase. Se a Data API estiver ativa, a anon key lê/escreve tudo | **Pendente** (depende do painel) | — |
| 2 | Média | `acesso.py` | `/convite` sem limite de tentativas | Corrigido (`app/limites.py`) | c51cb22 |
| 3 | Média | `whatsapp.py` | Sem limite de mensagens por usuário e texto livre sem teto | Corrigido (mensagens/minuto e texto limitado) | c51cb22 |
| 4 | Média | `comprovante.py` | Tipo do arquivo pelo mime declarado | Corrigido (confere os primeiros bytes do arquivo) | c51cb22 |
| 5 | Baixa | `db.py` | `DATABASE_URL` sem `sslmode=require` | Corrigido no código; **confirme no Render** que conecta | c51cb22 |
| 6 | Baixa | `main.py` | `/docs`, `/redoc`, `/openapi.json` públicos | Corrigido (desligados) | c51cb22 |
| 7 | Baixa | `main.py` | Comparação do token do webhook não constante e `TypeError` com não-ASCII | Corrigido (`_iguais`) | c51cb22 |
| 8 | Baixa | `main.py`, `paginas.py` | Sem cabeçalhos de segurança | Corrigido (nosniff, DENY, HSTS, CSP, Referrer-Policy) | c51cb22 |
| 9 | Baixa | `leads.py` | Origin forjável; limite por IP em memória zera no reinício | **Aceito**: porte do projeto; defesa real é o limite + isca | — |
| 10 | Baixa | `main.py` | Sem limite do corpo do webhook | Corrigido (1 MB, 413) | c51cb22 |
| 11 | Baixa | `recorrentes.py` | `UPDATE` sem `account_id` | Corrigido | c51cb22 |
| 12 | Baixa | `requirements.txt` | Versões não fixas | Corrigido, **exceto `anthropic`**, que ficou sem versão | c51cb22 |
| 13 | Baixa | `.gitignore` | Variantes de `.env` e `audit/raw` fora | Corrigido | c51cb22 |
| 14 | Baixa (nova) | `main.py` (`Content-Length`) | `int(header)` com valor não numérico gera erro 500 em vez de 400. Sem impacto de dados | **Pendente** (ajuste de 1 linha, não feito por estar fora da Fase 5) | — |

## 4. LGPD

### 4.1 Inventário de dados pessoais
Detalhado em `audit/fase3-lgpd.md`. Resumo: número de WhatsApp, nome (informado e do perfil), renda, gastos/entradas (favorecido, descrição, categoria), metas, objetivos, parcelas, vínculo do casal, estado da conversa, alertas enviados, lista de espera (nome, telefone, consentimento, UTM/gclid). **Não coletados:** CPF, e-mail, endereço, geolocalização, biometria. Comprovantes e holerites são lidos pela IA e descartados. Descrição de gasto em texto livre **pode** revelar dado sensível (saúde, religião); o bot não filtra isso.

### 4.2 Bases legais (sugeridas, a validar)
Serviço em si: execução de contrato (art. 7º, V). Alertas/lembretes: legítimo interesse (IX) ou consentimento. Lista de espera e cookies de Google: consentimento (I). Dados possivelmente sensíveis: art. 11 — **sem base definida**. **[JURÍDICO]**

### 4.3 Lacunas e ações

| # | Lacuna | Situação | Commit |
|---|---|---|---|
| L1 | Retenção | **Parcial.** Rotina diária (pelo `/cron`) apaga: mensagens processadas > 30 dias, conversas expiradas, lembretes e alertas > 90 dias, avisos não entregues > 30 dias, códigos de convite vencidos. **Ficam sem rotina:** dados financeiros, usuários inativos e leads (prazo é decisão sua) | aa30609 |
| L2 | `/apagar_meus_dados` incompleto | Corrigido: agora apaga também estado da conversa, nome do perfil e o cadastro da lista de espera. Continua mantendo o número e recusando quando há 2 membros (exige `/sair_casal`) — decisão de produto sua | aa30609 |
| L3 | Sem exportação | Corrigido: `/meus_dados` (com planilha) | 57cbc17 |
| L4 | Aviso de privacidade tardio | Corrigido: aviso com botão [Entendi] antes do uso | 57cbc17 |
| L5 | Políticas incompletas | Parcial: texto do bot cita IA, servidores fora do Brasil, retenção e removeu a promessa de que o responsável "não olha" os dados | aa30609 |
| L6 | Base legal do art. 11 | **Pendente, jurídico** | — |
| L7 | Plano de incidentes | Corrigido: `docs/plano_incidentes.md` | aa30609 |
| L8 | Trilha de auditoria de acesso | **Pendente**, decisão de custo/benefício | — |
| L9 | Dados reais no ambiente de desenvolvimento | **Pendente** (mesmo banco; testes automáticos usam SQLite em memória) | — |
| L10 | Lead sem versão do texto aceito e sem auto-revogação | **Pendente** | — |
| L11 | Encarregado, enquadramento de pequeno porte, DPAs | **Pendente, jurídico/painéis** | — |

## 5. Pendências que exigem sua decisão ou assessoria

1. **RLS no Supabase (#1, a mais importante):** no painel, confira se a Data API está ativa. Se estiver, ative RLS em todas as tabelas (ou desligue a Data API). Posso preparar o SQL (`ENABLE ROW LEVEL SECURITY` sem políticas, já que o app usa conexão direta), mas aplicar em produção é com você.
2. **Prazos de retenção** para dados financeiros, usuários inativos (sugestão: 12–24 meses com aviso) e leads (política promete "até 12 meses [revisar]"; sugestão 6 meses). Hoje esses dados ficam indefinidamente.
3. **Prazos inconsistentes** nas páginas: 15 dias (landing) × 30 dias (página de exclusão).
4. **Apagar o número** (`users`) quando o titular pedir "apagar tudo de vez", e apagar só a parte do usuário no casal.
5. **Base legal para dado sensível** (art. 11), **transferência internacional** (art. 33: Anthropic, Meta, Render, Google, talvez Supabase), encarregado e enquadramento de pequeno porte, revisão jurídica da política e dos termos (hoje "rascunho"). **[JURÍDICO]**
6. **Fixar a versão do `anthropic`** em `requirements.txt` (pergunto antes porque exige conferir a versão que funciona no Render).
7. **Rodar o gitleaks** na sua máquina para confirmar a ausência de segredos no histórico.

## 6. Limitações da auditoria

Não verifiquei: configuração do painel do Supabase (RLS, Data API, papel do banco, SSL, região), variáveis e logs do Render, escopo do token permanente da Meta, contratos/DPAs com operadores, onde a Anthropic retém dados, nem a criptografia em repouso dos provedores (não afirmo "criptografia" sem conferir a documentação). Também não testei em produção, só por código e testes automatizados. A varredura de segredos foi por padrões, não pelo gitleaks. Nenhuma auditoria garante ausência total de falhas.

## 7. Como testar manualmente as correções críticas e altas

- **Limite do `/convite` (#2):** com um número pendente, mande `/convite ERRADO` várias vezes seguidas; a partir de certo número o bot deve parar de aceitar tentativas.
- **Webhook (assinatura, tamanho):** `POST /webhook` sem `X-Hub-Signature-256` deve responder 403; corpo acima de 1 MB deve responder 413. Pelo WhatsApp, mensagens normais continuam funcionando.
- **Cabeçalhos e docs (#6, #8):** abra `/docs` (deve dar 404) e confira em `/privacidade` os cabeçalhos `X-Frame-Options`, `Content-Security-Policy` e `Strict-Transport-Security` (aba Rede do navegador).
- **Comprovante (#4):** envie um arquivo qualquer renomeado como PDF/imagem; o bot deve recusar. Uma foto real deve ser lida normalmente.
- **`/apagar_meus_dados` (L2):** registre um gasto, rode o comando, confirme [Apagar tudo] e verifique que `/resumo` volta vazio. No banco, `conversation_state` e `leads` sem linhas do seu número.
- **`/meus_dados` (L3):** rode o comando e confira se o resumo/planilha traz seus dados e nada de outras contas. No casal, os gastos "meu" do parceiro não aparecem em detalhe.
- **Aviso de privacidade (L4):** com um número novo liberado, o aviso com [Entendi] deve aparecer antes do primeiro registro.
- **Retenção (L1):** chame `/cron` com o `X-Cron-Secret` correto e veja no log do Render a linha "Retenção: {...}".
- **RLS (#1):** depois de ativar, tente ler a tabela `users` pela Data API com a anon key; deve voltar vazio ou negado.

## 8. Recomendações de médio prazo

Teste de penetração externo antes de abrir para o público; revisão jurídica da política de privacidade, dos termos e dos contratos/DPAs; segundo projeto Supabase para desenvolvimento; papel de banco com menos privilégios que o `postgres`; alerta automático de dependências (Dependabot ou `pip-audit` periódico); treinamento básico de LGPD e resposta a incidentes para quem tiver acesso ao banco.
