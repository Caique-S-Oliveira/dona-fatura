-- Objetivos de poupança e compras parceladas (Etapa 13). Rodar uma vez no SQL Editor do Supabase.
CREATE TABLE IF NOT EXISTS savings_goals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id UUID NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    target_amount NUMERIC(12, 2) NOT NULL CHECK (target_amount > 0),
    target_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, created_by_user_id)
        REFERENCES members (account_id, user_id),
    UNIQUE (account_id, normalized_name)
);

CREATE TABLE IF NOT EXISTS savings_contributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id UUID NOT NULL REFERENCES savings_goals (id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id UUID NOT NULL,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    contribution_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, created_by_user_id)
        REFERENCES members (account_id, user_id)
);

CREATE INDEX IF NOT EXISTS savings_contributions_goal_idx
    ON savings_contributions (goal_id);

CREATE TABLE IF NOT EXISTS installments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id UUID NOT NULL,
    description TEXT NOT NULL,
    installment_amount NUMERIC(12, 2) NOT NULL CHECK (installment_amount > 0),
    total_installments INTEGER NOT NULL CHECK (total_installments BETWEEN 1 AND 360),
    first_due_date DATE NOT NULL,
    due_day INTEGER NOT NULL CHECK (due_day BETWEEN 1 AND 31),
    scope TEXT NOT NULL DEFAULT 'conjunto'
        CHECK (scope IN ('meu', 'conjunto')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, created_by_user_id)
        REFERENCES members (account_id, user_id)
);
