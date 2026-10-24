-- Complemento: renda esperada por mês (/renda), para quem tem renda que varia (autônomos).
-- Rode no SQL Editor do Supabase.

-- Um valor por pessoa por mês (month = sempre o dia 1). Mês sem linha usa o padrão do /inicio
-- (members.expected_income).
CREATE TABLE IF NOT EXISTS income_plans (
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    month DATE NOT NULL CHECK (EXTRACT(DAY FROM month) = 1),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, user_id, month)
);

-- Sem política: a API pública do Supabase não enxerga a tabela; o bot acessa pela conexão direta.
ALTER TABLE income_plans ENABLE ROW LEVEL SECURITY;
