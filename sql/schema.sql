CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id UUID NOT NULL REFERENCES users (id),
    name TEXT NOT NULL DEFAULT 'Minha conta',
    mode TEXT NOT NULL DEFAULT 'individual'
        CHECK (mode IN ('individual', 'couple', 'group')),
    invitation_code TEXT UNIQUE,
    invitation_expires_at TIMESTAMPTZ,
    whatsapp_group_id TEXT,
    whatsapp_group_invite_link TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS members (
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users (id),
    role TEXT NOT NULL DEFAULT 'partner'
        CHECK (role IN ('owner', 'partner')),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS members_one_owner_per_account_idx
    ON members (account_id)
    WHERE role = 'owner';

CREATE TABLE IF NOT EXISTS categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id UUID,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    type TEXT NOT NULL
        CHECK (type IN ('Fixo', 'Variável', 'Assinatura', 'Investimento', 'Reserva de emergência')),
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, normalized_name),
    UNIQUE (account_id, id),
    FOREIGN KEY (account_id, created_by_user_id)
        REFERENCES members (account_id, user_id)
);

CREATE TABLE IF NOT EXISTS goals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    member_user_id UUID,
    type TEXT NOT NULL
        CHECK (type IN ('Fixo', 'Variável', 'Assinatura', 'Investimento', 'Reserva de emergência')),
    value_type TEXT NOT NULL
        CHECK (value_type IN ('percentage', 'amount')),
    value NUMERIC(12, 2) NOT NULL CHECK (value >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (value_type = 'percentage' AND value <= 100)
        OR value_type = 'amount'
    ),
    FOREIGN KEY (account_id, member_user_id)
        REFERENCES members (account_id, user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS goals_account_type_idx
    ON goals (account_id, type)
    WHERE member_user_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS goals_member_type_idx
    ON goals (account_id, member_user_id, type)
    WHERE member_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS recurring_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id UUID NOT NULL,
    category_id UUID,
    payee TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    frequency TEXT NOT NULL DEFAULT 'monthly'
        CHECK (frequency IN ('weekly', 'monthly', 'yearly')),
    next_due_date DATE,
    scope TEXT NOT NULL DEFAULT 'meu'
        CHECK (scope IN ('meu', 'conjunto')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, created_by_user_id)
        REFERENCES members (account_id, user_id),
    FOREIGN KEY (account_id, category_id)
        REFERENCES categories (account_id, id),
    UNIQUE (account_id, id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id UUID NOT NULL,
    category_id UUID,
    recurring_transaction_id UUID,
    transaction_type TEXT NOT NULL
        CHECK (transaction_type IN ('income', 'expense')),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    description TEXT,
    payee TEXT,
    transaction_date DATE NOT NULL,
    scope TEXT NOT NULL DEFAULT 'meu'
        CHECK (scope IN ('meu', 'conjunto')),
    source TEXT NOT NULL
        CHECK (source IN ('paystub', 'receipt', 'manual')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    voided_at TIMESTAMPTZ,
    FOREIGN KEY (account_id, created_by_user_id)
        REFERENCES members (account_id, user_id),
    FOREIGN KEY (account_id, category_id)
        REFERENCES categories (account_id, id),
    FOREIGN KEY (account_id, recurring_transaction_id)
        REFERENCES recurring_transactions (account_id, id)
);

CREATE INDEX IF NOT EXISTS transactions_account_date_idx
    ON transactions (account_id, transaction_date)
    WHERE voided_at IS NULL;
CREATE INDEX IF NOT EXISTS transactions_account_scope_date_idx
    ON transactions (account_id, scope, transaction_date)
    WHERE voided_at IS NULL;

CREATE TABLE IF NOT EXISTS classification_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_by_user_id UUID NOT NULL,
    category_id UUID NOT NULL,
    normalized_payee TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, created_by_user_id)
        REFERENCES members (account_id, user_id),
    FOREIGN KEY (account_id, category_id)
        REFERENCES categories (account_id, id),
    UNIQUE (account_id, normalized_payee)
);

CREATE TABLE IF NOT EXISTS processed_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    whatsapp_message_id TEXT NOT NULL UNIQUE,
    sender_phone_number TEXT NOT NULL,
    account_id UUID REFERENCES accounts (id) ON DELETE SET NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'processing', 'processed', 'failed'))
);

CREATE TABLE IF NOT EXISTS conversation_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number TEXT NOT NULL UNIQUE,
    user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    account_id UUID REFERENCES accounts (id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sent_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    alert_type TEXT NOT NULL,
    deduplication_key TEXT NOT NULL,
    period_start DATE,
    period_end DATE,
    whatsapp_message_id TEXT,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (account_id, user_id)
        REFERENCES members (account_id, user_id),
    UNIQUE (account_id, user_id, deduplication_key)
);
