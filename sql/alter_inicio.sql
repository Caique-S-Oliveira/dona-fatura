-- Renda mensal esperada de cada pessoa na conta (Etapa 5). Rodar uma vez no SQL Editor do Supabase.
ALTER TABLE members
    ADD COLUMN IF NOT EXISTS expected_income NUMERIC(12, 2) CHECK (expected_income >= 0);
