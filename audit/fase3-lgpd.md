# Fase 3 — Conformidade com a LGPD (Dona Fatura)

Projeto único: Dona Fatura (bot de WhatsApp + API FastAPI + landing page estática).
Base: `sql/*.sql`, `app/` (privacidade, inicio, leads, paginas, ia, alertas, acesso), `landing/` (config, script, privacidade.html),
`audit/fase2-revisao-manual.md` e `audit/raw/`. Nenhum código foi alterado (correções ficam para a Fase 4).
Observação: não sou advogado; os itens marcados **[JURÍDICO]** precisam de revisão de quem é.

## 1. Inventário de dados pessoais

| Dado | Onde (tabela.campo / arquivo) | Titular | Sensível (art. 5º, II)? |
|---|---|---|---|
| Número de WhatsApp | `users.phone_number`, `conversation_state.phone_number`, `processed_messages.sender_phone_number`, `leads.telefone` | usuário / lead | Não |
| Nome informado no /inicio | `users.display_name` | usuário | Não |
| Nome do perfil do WhatsApp | `users.profile_name` (vem da Meta; mostrado ao admin nos pedidos de acesso) | usuário | Não |
| Renda esperada / líquida | `members.expected_income`, transações `income` | usuário | Não (financeiro, mas pessoal) |
| Gastos: valor, data, favorecido, descrição, categoria | `transactions.*`, `recurring_transactions.*`, `classification_rules.normalized_payee` | usuário | **Possível**: favorecido/descrição podem revelar saúde (farmácia, consulta), religião (dízimo), filiação etc. O bot não filtra isso |
| Metas, objetivos, parcelas | `goals`, `savings_goals`, `savings_contributions`, `installments` (nomes livres, ex.: "cirurgia") | usuário | Possível, igual ao acima |
| Vínculo do casal, código de convite, grupo | `accounts`, `members`, `accounts.whatsapp_group_*` | usuário + parceiro | Não |
| Estado da conversa (pode guardar valor/favorecido pendente) | `conversation_state.data` (JSONB) | usuário | Possível |
| Alertas e lembretes enviados | `sent_alerts`, `reminder_log`, `pending_notices.message` | usuário | Não |
| Cadastro da lista de espera: nome, telefone, data do consentimento | `leads.nome/telefone/consentimento_em` | lead | Não |
| Origem do clique: gclid, UTM, variante, página | `leads.*` | lead | Não (identificador de publicidade) |
| IP do visitante | Não é gravado no banco. Fica só em memória (limite de tentativas, `leads.py`) e nos logs de acesso do Render/Cloudflare | visitante | Não |
| Cookies/identificadores do Google (Analytics/Ads) | Só após aceite; hoje `GA4_ID` e `ADS_ID` estão vazios, então **nada é carregado** | visitante | Não |
| Armazenamento local do navegador | `localStorage.df_consent`, `sessionStorage.df_origem` | visitante | Não |
| Fotos/PDF de comprovante e holerite | **Não guardados**: lidos pela IA e descartados | usuário | Holerite pode conter CPF, cargo, descontos (sindicato, plano de saúde) mesmo sendo descartado: passa pela Anthropic |
| Logs | Sem corpo de mensagem, sem token, telefone mascarado; ids de usuário (UUID) aparecem em `alertas.py` | — | Não |

Dados que **não** são coletados: CPF, endereço, e-mail, geolocalização, biometria. Telefone do titular é o identificador.

## 2. Base legal (art. 7º e 11)

| Tratamento | Base sugerida | Documentada? | Situação |
|---|---|---|---|
| Cadastro, registro de gastos/rendas, resumos, metas, previsão (o serviço em si) | Execução de contrato / procedimentos preliminares (art. 7º, V) | Não | Os textos não nomeiam a base. **[JURÍDICO]** |
| Envio dos dados à Anthropic para ler comprovante/holerite e interpretar frases | Mesma base (necessário ao serviço) + transparência | Citada só como "com quem passa" | Falta dizer que é fora do Brasil (ver item 9) |
| Alertas e lembretes de inatividade | Legítimo interesse (art. 7º, IX) ou consentimento | Não | Há botão "Parar lembretes", mas a base não está escrita. Fora da janela de 24h usa modelo pago da Meta |
| Lista de espera | Consentimento (art. 7º, I) | **Sim**, na política da landing | Ok, ver item 4 |
| UTM/gclid/variante junto ao lead | Legítimo interesse (declarado) | Sim | Ver item 3: gclid + telefone é identificador de publicidade ligado a pessoa; considerar consentimento |
| Google Analytics/Ads | Consentimento | Sim | Efetivo (ver item 12) |
| Dados possivelmente sensíveis (descrição de gasto) | Art. 11: consentimento específico ou outra hipótese do art. 11, II | **Não** | Lacuna. **[JURÍDICO]** |
| Armazenar `profile_name` e número de quem ainda não foi liberado | Legítimo interesse (controle de acesso) | Não | Lacuna |

## 3. Finalidade e necessidade (art. 6º)

- `users.profile_name`: usado só para o admin identificar o pedido e como nome no lembrete quando falta `display_name`. Justificável; **declarar na política**.
- `leads.gclid` + `utm_*` + `pagina` + `variante`: finalidade é medir anúncio. Não precisa do telefone para isso; ao menos **definir prazo curto** (ver item 7) ou gravar só agregado.
- `processed_messages.sender_phone_number`: só serve para anti-repetição; o `whatsapp_message_id` basta. Candidato a **remover o telefone** ou apagar registros antigos.
- `conversation_state.phone_number` redundante com `user_id`, mas necessário antes do cadastro. Manter, com expiração (ver item 7).
- `transactions.description` e `payee` em texto livre: necessários, mas é onde dado sensível pode entrar. **Justificar na política**; não há como minimizar sem perder o produto.
- O bot não pede CPF nem dados bancários. Bom. O holerite pode conter CPF, mas é opcional e descartado.

## 4. Consentimento

- **Landing (lista de espera):** caixa **não** pré-marcada (`script.js:198`, `type: checkbox` sem `checked`); o envio exige marcar (`script.js:234`); o servidor recusa sem `consentimento` (`leads.py`) e grava `consentimento_em`. Atende bem. Faltam: guardar **qual versão do texto/política** foi aceita, e um jeito de revogar sem depender de e-mail.
- **Cookies:** Consent Mode v2 com tudo negado por padrão; o script do Google só é carregado após o aceite; há “Preferências de cookies” no rodapé. Efetivo.
- **Bot (WhatsApp):** o usuário é cadastrado no primeiro contato e só recebe o aviso de privacidade ao final do /inicio (`inicio.py:36`, texto curto que não cita IA nem Meta). **Não há registro de aceite** (nem coluna, nem data). A base é contrato, não consentimento, mas a transparência vem **depois** de os dados já terem sido gravados e, no caso de foto/PDF, enviados à IA. Recomendo mostrar o aviso e registrar o "ok" antes do primeiro registro. Isso muda o comportamento visível: **sinalizar antes de implementar**.
- **Casal:** o parceiro enxerga renda completa e gastos conjuntos. Há a pergunta de modo ("tudo junto" / "com gastos pessoais"), mas não há aviso explícito de que a renda fica visível ao parceiro. Verificar o texto do /entrar.

## 5. Transparência (política de privacidade)

Existem duas: `landing/privacidade.html` (site; marcada "Rascunho") e `/privacidade` servida por `app/paginas.py` (bot, exigida pela Meta). Também o comando `/privacidade`.

Lacunas encontradas:
- Controlador: nome da pessoa física e e-mail — ok. Sem CPF/endereço (não obrigatório para PF, mas **[JURÍDICO]**).
- **Prazo de retenção do bot não aparece** em nenhuma das duas páginas do bot (só a landing cita 12 meses, com "[revisar prazo]").
- Bases legais não aparecem na política do bot (aparecem só na da landing).
- **Transferência internacional** não é mencionada (Anthropic, Meta, Supabase, Render, Google).
- O texto do bot diz "banco protegido por senha" e "não olha seus dados a não ser que você peça ajuda": promessa de conduta que o administrador não consegue provar tecnicamente; o CLAUDE.md pede honestidade (admin do banco **consegue** ver). A página do bot já omite isso; a landing diz "quem administra o banco tem acesso técnico". **Alinhar os três textos.**
- Não cita: lembretes automáticos e uso de modelos pagos da Meta; o `profile_name`; quem é o encarregado; direito de revisão/oposição; direito de reclamar à ANPD.
- Landing: o link para a política do bot só aparece com `URL_APP` preenchida (está preenchida em `config.js`; conferir se renderiza).
- Cookie banner/GA: política da landing cobre. Termos de uso são rascunho.

## 6. Direitos do titular (arts. 18 a 20)

| Direito | Como o sistema atende hoje | Lacuna |
|---|---|---|
| Confirmação / acesso | `/resumo`, `/fixos`, `/metas` mostram partes; **não há exportação completa** | Falta comando de acesso/exportação (ex.: `/meus_dados` com CSV/texto). Hoje depende de e-mail manual |
| Correção | `/desfazer`, editar metas/objetivos/parcelas, `/inicio` refaz nome/renda | Não há edição de transação antiga além de desfazer o último; aceitável |
| Portabilidade | Não implementada | Mesma lacuna da exportação |
| Anonimização / bloqueio | Não há | Possível via e-mail; `access_status = 'bloqueado'` existe, mas é ato do admin, não do titular |
| Eliminação | `/apagar_meus_dados` (com confirmação) | **Incompleto**, ver abaixo |
| Revogação de consentimento | Landing: só por e-mail; lembretes: "Parar lembretes" | Lead não tem como sair sozinho |
| Informação sobre compartilhamento | Política (parcial) | Ver item 5 |

Problemas concretos em `/apagar_meus_dados` (`privacidade.py`, `_apagar`):
1. **Mantém o número** (`users`) e `accounts`/`members` por escolha de produto — o texto avisa. Para o titular que quer sair de vez, só por e-mail (30 dias, na página de exclusão; a landing promete 15 dias para direitos: **inconsistência de prazos**).
2. **Não apaga** `conversation_state`, `reminder_log`, `pending_notices`, nem `users.profile_name`. (`savings_contributions` sai por CASCADE de `savings_goals`; `processed_messages` é apagada.)
3. **Recusa-se** quando a conta tem 2 membros ("não sei apagar só a sua parte"): o titular no casal só consegue eliminar passando por `/sair_casal` antes. Funciona, mas é um obstáculo ao direito; considerar apagar só a parte do usuário.
4. **Não apaga o lead** da landing (tabela `leads`), mesmo que a mesma pessoa vire usuária.
5. Não há trilha de que a eliminação ocorreu (e não deve haver dado pessoal nela, mas um registro mínimo "pedido atendido em ..." sem telefone seria útil como prova).

## 7. Retenção e eliminação (arts. 15 e 16)

**Não há rotina de retenção.** Nenhum job apaga ou anonimiza nada por tempo. Tabela a tabela:

| Dado | Retenção hoje | Proposta (decisão sua/jurídica) |
|---|---|---|
| `transactions` e demais dados financeiros | indefinida, enquanto a conta existir | Enquanto o usuário usar o serviço; apagar após N meses de inatividade (sugestão: 12 a 24) com aviso prévio por modelo |
| `users` bloqueado/negado ou pendente sem conta | indefinida | Apagar pendentes/negados após 30–90 dias |
| `processed_messages` | indefinida (cresce sempre, com telefone) | Apagar após 7–30 dias (só serve para anti-repetição) |
| `conversation_state` | tem `expires_at`, mas **nada o remove** | Apagar expirados diariamente (pode ir no /cron) |
| `reminder_log`, `sent_alerts` | indefinida | 90 dias |
| `pending_notices` | até ser entregue | Se o parceiro nunca voltar, expirar em 30 dias |
| `leads` | indefinida no código; a política promete "até 12 meses [revisar]" | Implementar a rotina para cumprir a promessa; ou prazo menor (ex.: 6 meses) |
| `accounts.invitation_code` | expira em 48h, mas o código fica no banco | Limpar após expirar |
| Logs do Render | definido pelo provedor | Conferir no painel |

## 8. Minimização em ambientes não produtivos

- Não há staging; só produção e máquina local usando o **mesmo `DATABASE_URL`** (o `.env` aponta para o Supabase real; `scripts/dados_teste.py` e `apagar_dados_teste.py` gravam na conta real, marcando `[teste]`). Risco: testes manuais e scripts em cima de dados reais. Os testes automatizados (`tests/`) usam SQLite em memória, sem dados reais — ok.
- Sugestão: um segundo projeto Supabase (grátis) só para desenvolvimento, ou confirmar que o piloto não terá mais de poucos usuários reais.
- Logs de produção: sem conteúdo. Ok.
- `audit/raw/` contém saída de scanners; não tem dado pessoal, mas deve ficar fora do Git (ver `.gitignore`, achado 13 da Fase 2).

## 9. Compartilhamento, operadores e transferência internacional (art. 33)

| Terceiro | O que recebe | Papel | Local provável | Contrato / DPA |
|---|---|---|---|---|
| Meta (WhatsApp Cloud API) | Número, texto, mídia, nome do perfil, grupo | Operador/controlador próprio | EUA/global | Termos da plataforma Meta; confirmar aceite |
| Anthropic (API Claude) | Imagem/PDF de comprovante e holerite, frases livres, descrição de gasto para categorizar, **números calculados** no texto do /diagnostico | Operador | EUA | Termos comerciais da API; confirmar retenção (padrão de API não treina com dados, **confirmar na conta**) |
| Supabase | Todo o banco | Operador | **Região do projeto: não verificável por código** | DPA do Supabase; confirmar região |
| Render | Tráfego e logs; processa tudo em memória | Operador | EUA/Europa conforme região | DPA do Render |
| Cloudflare Pages (landing, `*.pages.dev`) | IP/headers de visitantes, logs | Operador | Global | Termos Cloudflare |
| Google (Analytics/Ads) | Só se houver aceite e IDs preenchidos | Controlador próprio | EUA | Termos do Google |
| cron-job.org | Só chama `/cron` com segredo; **não recebe dado pessoal** | — | Alemanha | — |

Há transferência internacional (Anthropic, Meta, Render, Google, talvez Supabase). Base do art. 33 a documentar (cláusulas-padrão/contrato do operador, ou consentimento específico). **[JURÍDICO]** A política não menciona isso.

## 10. Segurança dos dados (arts. 46 a 49)

- Em repouso: criptografia de disco do Supabase/Render é do provedor; **não afirmei nem devo afirmar "criptografia"** antes de conferir a documentação (regra do CLAUDE.md). Não há criptografia em nível de campo.
- Acesso por necessidade: aplicação conecta com um único `DATABASE_URL` (provavelmente superusuário `postgres` via pooler) — sem papel de mínimo privilégio. Só `leads` tem RLS (Fase 2, achado 1, alta a confirmar).
- Trilha de auditoria: **não existe** log de quem acessou/alterou dados; o admin vê números mascarados nos comandos, mas o acesso direto ao banco não deixa trilha no app. `reminder_log`/`sent_alerts` não são trilha de acesso.
- Controle: comandos de admin protegidos por `ADMIN_PHONE`; aprovação manual de novos usuários (bom para o piloto).
- Privacidade entre parceiros: separação `meu`/`conjunto` verificada na Fase 2.

## 11. Incidentes (art. 48)

Não há plano nem registro. Proposto (a documentar na Fase 4/entrega, sem inventar contatos):
1. Detectar: alertas do Render/Supabase, e-mail do provedor, aviso de usuário.
2. Registrar: arquivo `docs/plano_incidentes.md` com data, o que aconteceu, dados e titulares afetados, medidas.
3. Avaliar risco/dano relevante; se houver, comunicar à **ANPD** e aos titulares em prazo razoável (a ANPD indica 3 dias úteis na Res. CD/ANPD nº 15/2024 — **[JURÍDICO]** confirmar), com a descrição da natureza dos dados, medidas e contato.
4. Rotacionar segredos (WhatsApp token, DATABASE_URL, ANTHROPIC_API_KEY, CRON_SECRET, WHATSAPP_APP_SECRET) — exige sua aprovação, em produção.
5. Canal para comunicar titulares: o próprio WhatsApp (dentro de janela) e e-mail do projeto.

## 12. Cookies e rastreadores

- Banco do projeto: nenhum cookie próprio, nenhum rastreador no bot.
- Landing: Google Analytics/Ads **só após aceite**; IDs hoje vazios (nenhum script externo carregado). Estado: `localStorage.df_consent` (escolha) e `sessionStorage.df_origem` (UTM) — armazenamento estritamente necessário/funcional, mas ele guarda UTM/gclid mesmo **antes** do aceite e os envia no lead; está declarado na política. Declarar no banner também.
- Verificar nas Etapas finais: fontes ou scripts externos na landing (grep por `fonts.googleapis`, CDNs) que façam o navegador contatar terceiros antes do aceite.
- Banner efetivo conforme `script.js:84-135` (default negado → carrega só em "granted").

## 13. Encarregado (DPO) e canal de contato

- Canal: `donafatura.app@gmail.com`, citado na landing, na política do bot e na página de exclusão — **existe**. O prazo de resposta diverge (15 dias na landing × 30 dias na página de exclusão).
- **Não há encarregado nomeado** nem indicação de quem é (a LGPD exige indicar; a ANPD dispensa agentes de tratamento de pequeno porte, Res. CD/ANPD nº 2/2022, mas o canal continua obrigatório). **[JURÍDICO]** confirmar enquadramento e se vale nomear o próprio responsável.
- Não há formulário; só e-mail. Suficiente.

## Resumo das lacunas (para a Fase 4)

| # | Lacuna | Gravidade LGPD | Tipo |
|---|---|---|---|
| L1 | Sem rotina de retenção/eliminação (processed_messages, conversation_state, leads, inativos) | Alta | Código + decisão de prazos |
| L2 | `/apagar_meus_dados` incompleto (conversation_state, reminder_log, pending_notices, profile_name, leads) e recusa no casal | Alta | Código |
| L3 | Sem exportação/acesso aos dados (art. 18, II e V) | Alta | Código novo (comando visível ao usuário) |
| L4 | Aviso de privacidade só ao fim do /inicio, sem registro de ciência; sem menção à IA/Meta/transferência | Média | Código + texto (muda comportamento) |
| L5 | Políticas incompletas e inconsistentes (retenção, bases, internacional, ANPD, prazos 15×30 dias, promessa sobre acesso do admin) | Média | Texto |
| L6 | Sem base legal documentada para dado potencialmente sensível (art. 11) | Média | **Decisão jurídica** |
| L7 | Sem plano de incidentes | Média | Documento |
| L8 | Sem trilha de auditoria de acesso | Baixa/Média | Decisão (custo/benefício) |
| L9 | Dados reais em ambiente de desenvolvimento (mesmo banco) | Baixa | Decisão |
| L10 | Lead sem versão do texto aceito e sem auto-revogação | Baixa | Código leve |
| L11 | Encarregado/enquadramento de pequeno porte e DPAs dos operadores | — | **Decisão jurídica / conferência em painéis** |

## Decisões que preciso de você antes da Fase 4

1. **Prazos de retenção** (inatividade de usuários, leads, logs técnicos) — proponho: processed_messages 30 dias, conversation_state expirados limpos, reminder/sent_alerts 90 dias, leads 6 meses, usuários inativos 12 meses com aviso. Aceita ou ajusta?
2. **Exportação**: comando `/meus_dados` que envia um resumo em texto/CSV pelo WhatsApp. Pode criar (muda o que o usuário vê)?
3. **Aviso antes do uso**: mostrar o aviso de privacidade com botão [Entendi] antes do primeiro registro e gravar a data? (muda o fluxo do /inicio)
4. **Apagar tudo** deve remover também o número (`users`) quando a pessoa pedir "apagar tudo de vez"? Hoje mantém por escolha de produto.
5. Região do Supabase/Render e aceite dos DPAs: preciso que você confirme nos painéis (não consigo daqui).

Fim da Fase 3. Não avancei para a Fase 4.
