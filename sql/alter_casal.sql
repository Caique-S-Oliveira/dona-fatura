-- Etapa 15: modo casal. Como o casal quer registrar os gastos:
--   'junto'   = tudo junto (padrão): gastos são do casal, "meu" só com o sufixo
--   'pessoal' = com gastos pessoais: o bot pergunta [Meu] [Conjunto] a cada gasto
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS privacy_mode TEXT NOT NULL DEFAULT 'junto'
        CHECK (privacy_mode IN ('junto', 'pessoal'));
