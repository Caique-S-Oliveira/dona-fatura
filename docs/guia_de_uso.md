# Guia de uso — Dona Fatura

A Dona Fatura é uma assistente financeira no WhatsApp. Você conta o que ganha e o que gasta, ela compara com as suas metas, prevê como o mês termina e diz o que corrigir. Ela é direta e objetiva: avisa quando algo foge do plano, sem sermão.

## Comece em 3 passos

1. Mande **/inicio**. Em cerca de 2 minutos você informa nome, renda e metas.
2. Registre seus gastos: **/gasto 45,90 mercado** (ou escreva "gastei 45 no mercado").
3. Depois de alguns dias, use **/resumo**, **/previsao** e **/diagnostico**.

Dica: o /ajuda mostra a lista de comandos a qualquer momento.

---

## Registrar

| Comando | Para que serve | Exemplo |
|---|---|---|
| **/gasto VALOR DESCRIÇÃO** | Registra uma saída. Ela sugere a categoria e você confirma com [Sim] ou [Corrigir]. | `/gasto 45,90 mercado` |
| **/entrada VALOR DESCRIÇÃO** | Registra uma entrada (salário, extra). Sem valor, ela aceita a foto/PDF do holerite, que é opcional. | `/entrada 3000 salário` |
| **/desfazer** | Desfaz o último registro, com confirmação. Também volta um pagamento de parcela. | `/desfazer` |

Outras formas de registrar:
- **Frase livre:** "gastei 45 no mercado".
- **Comprovante:** mande a foto ou o PDF do pagamento/Pix. Ela lê valor, data e favorecido, sugere a categoria e pede confirmação. O arquivo é descartado depois da leitura.
- **Nada é salvo sem a sua confirmação** (botões [Sim] [Corrigir]).
- Ao corrigir uma categoria, ela **aprende**: da próxima vez, o mesmo favorecido já vem na categoria certa.
- Se o mesmo favorecido aparecer com valor parecido em 2 meses ou mais, ela pergunta se é uma conta recorrente.

## Acompanhar

| Comando | Para que serve |
|---|---|
| **/resumo** | Resumo do mês: entradas, saídas e variação em relação ao mês passado. |
| **/resumo semana** | Resumo da semana. |
| **/previsao** | Como o mês termina: entradas − saídas − contas que ainda vencem − gasto médio dos dias restantes. |
| **/diagnostico** | Compara o real com a meta de cada tipo, mostra só o que está fora e quanto cortar ou guardar por semana para bater as metas. |
| **/grafico previsao** | Gráfico (imagem) com o que deveria estar, o que está e a projeção do mês. |
| **/fixos** | Contas fixas e assinaturas: pagas, a vencer e atrasadas. |

## Planejar

| Comando | Para que serve | Exemplo |
|---|---|---|
| **/inicio** | Configura nome, renda e metas (em R$, em % da renda ou no atalho 50/30/20). | `/inicio` |
| **/metas** | Vê e altera as metas por tipo (Fixo, Variável, Assinatura, Investimento, Reserva de emergência). | `/metas variável 1500` |
| **/categorias** | Lista as categorias (Moradia, Mercado, Transporte, Saúde, Lazer…) e permite criar novas. | `/categorias` |
| **/objetivos** | Metas de poupança com nome, valor e prazo. Ela diz quanto falta e quanto guardar por mês. Dá para editar e excluir pela lista. | `/objetivos novo viagem 4000 12/2026` |
| **/parcelas** | Compras parceladas. Mostra o que falta pagar; as parcelas que ainda vencem entram na previsão. | `/parcelas nova geladeira 200 10x` |
| **/pagar** | Marca uma parcela como paga e registra a saída. Escolha por botões ou pelo nome. | `/pagar geladeira` |

Dica: `/objetivos`, `/parcelas` e `/categorias` abrem uma lista interativa; é só tocar no item.

## A dois (casal)

| Comando | Para que serve |
|---|---|
| **/casal** | Gera um código (vale 48h, uso único) para o parceiro. |
| **/entrar CÓDIGO** | O parceiro usa o código e entra na mesma conta. |
| **/sair_casal** | Separa as contas, com confirmação. Cada um fica com seus gastos "meu" e metas individuais, e os dois ficam com uma cópia do histórico conjunto. |

Como funciona a privacidade no casal:
- Ao entrar, vocês escolhem **uma vez**: "tudo junto" ou "com gastos pessoais".
- Em "com gastos pessoais", cada registro pergunta [Meu] [Conjunto].
- Em qualquer modo, o sufixo **meu** marca um gasto como privado: `/gasto 30 padaria meu`. O parceiro vê só o total somado, nunca o detalhe.
- A renda de cada um é visível ao parceiro.
- As metas podem ser do casal e também individuais.

## Dados e privacidade

| Comando | Para que serve |
|---|---|
| **/privacidade** | Explica o que é guardado e quem tem acesso (inclusive que o administrador do banco consegue ver os dados). |
| **/apagar_meus_dados** | Apaga tudo, com botões [Apagar tudo] [Cancelar]. Não tem volta. |

## Alertas automáticos

No máximo 3 mensagens por semana, por volta das 10h. Ordem de prioridade:
1. Resumo semanal (inclui aviso de meta em 80% e 100%).
2. Conta, assinatura ou parcela vencendo amanhã.
3. Gasto muito acima do normal.
4. Lembrete depois de 4 dias sem registros.

---

## Para ter a melhor experiência

1. **Registre na hora.** Gastou, mande uma frase ou a foto do comprovante. Deixar acumular é o que mais atrapalha a previsão.
2. **Configure as metas com calma no /inicio.** Se não souber por onde começar, use o atalho 50/30/20 e ajuste depois no /metas.
3. **Corrija a categoria quando errar.** Ela aprende e acerta mais nas próximas vezes.
4. **Cadastre o que é fixo:** assinaturas, aluguel e parcelas. Assim a /previsao considera o que ainda vai vencer.
5. **Use o /diagnostico no meio do mês**, quando ainda dá tempo de ajustar, e não só no fim.
6. **Errou um registro?** Use o /desfazer logo em seguida.
7. **Mensagens curtas funcionam melhor.** Um registro por mensagem, com valor e descrição.
8. **Em casal, combinem o modo de privacidade** antes de começar a registrar.
9. **Se ela não entender,** mande o comando direto (por exemplo `/gasto 20 café`). Comandos são mais rápidos e não usam IA.
10. **Confira os números importantes.** A Dona Fatura ajuda a organizar, mas não substitui extrato do banco nem consultoria financeira.

## Dúvidas comuns

- **Ela respondeu "Ainda estou aprendendo isso".** A frase não foi entendida. Tente um comando com `/` ou reescreva de forma simples.
- **Não recebi o alerta semanal.** Alertas em texto só chegam se você falou com ela nas últimas 24h (regra do WhatsApp). Mande qualquer mensagem de vez em quando.
- **Meu acesso está pendente.** Novos números precisam ser liberados pelo administrador.
- **Quero recomeçar.** Use /apagar_meus_dados e depois /inicio.
