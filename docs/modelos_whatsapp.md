# Modelos (templates) do WhatsApp para criar na Meta

Só serão usados quando `MODELOS_ATIVOS=1` e só para quem está fora da janela de 24h.
Em todos: **Categoria = Utilidade**, **Idioma = Português (BR)**, sem cabeçalho, rodapé nem botões.
Os nomes abaixo precisam ficar exatamente assim (estão em `app/alertas.py`).
A Meta não aceita variável no começo ou no fim do texto, nem quebra de linha dentro de variável;
por isso cada texto termina em frase fixa e as variáveis vêm em uma linha só.

## 1. `resumo_semanal` (5 variáveis)

Texto:
```
Resumo da sua semana ({{1}}): entradas {{2}}, saídas {{3}}, saldo {{4}}. {{5}} Para ver o resumo completo, envie /resumo.
```
Exemplos: `12 a 18/10` | `R$ 1.000,00` | `R$ 100,00` | `R$ 900,00` | `Variável: 85% da meta (R$ 850,00 de R$ 1.000,00).`

Observação: a variável 5 leva os avisos de meta (80% e 100%) e, na primeira semana do mês,
o resumo do mês passado; sem avisos, vai "Nenhuma meta perto do limite.".

## 2. `conta_vencendo_amanha` (3 variáveis)

Texto:
```
Vencimento amanhã ({{1}}): {{2}}. Total: {{3}}. Para ver suas contas, envie /fixos.
```
Exemplos: `20/10` | `Netflix: R$ 39,90; Geladeira (parcela 3/10): R$ 200,00` | `R$ 239,90`

## 3. `lembrete_registro` (2 variáveis + 2 botões)

O nome pode ser trocado pela variável `MODELO_LEMBRETE` no .env (padrão `lembrete_registro`).

Texto:
```
Oi, {{1}}! Seu último registro na Dona Fatura foi em {{2}}. Que tal anotar seus gastos de hoje? É rapidinho.
```
Exemplos: `Ana` | `18/10`

Botões (tipo **Resposta rápida**, nesta ordem):
1. `Registrar agora`
2. `Parar lembretes`

O bot envia o payload `lembrete_registrar` e `lembrete_parar` nos botões; "Registrar agora" responde
com como registrar (/gasto, comprovante) e "Parar lembretes" desliga os lembretes (`/lembretes` religa).

Quando sai: o usuário está há `INATIVIDADE_DIAS` dias (padrão 3) sem mandar mensagem, e de novo aos 7 dias;
depois para até ele voltar. Respeita o limite de 3 mensagens por semana e só vai com `MODELOS_ATIVOS=1`.

Atenção: este é o mais sujeito a que a Meta reclassificar como Marketing (é um lembrete para usar o
serviço). Se isso acontecer, o custo por envio é maior. Se a Meta recusar o envio (modelo não aprovado ou
pausado, número inválido), o bot não tenta de novo no mesmo dia e grava o motivo no log e na tabela
`reminder_log`.
