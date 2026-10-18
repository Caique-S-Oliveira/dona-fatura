-- /pagar parcelas (Etapa 18). Rodar uma vez no SQL Editor do Supabase.
-- paid_installments: quantas parcelas foram pagas de fato (NULL = parcela antiga: conta como paga ao passar a data).
-- last_payment_id: saída do último pagamento, para o /desfazer voltar a contagem.
ALTER TABLE installments
    ADD COLUMN IF NOT EXISTS paid_installments INTEGER
        CHECK (paid_installments >= 0),
    ADD COLUMN IF NOT EXISTS last_payment_id UUID;
