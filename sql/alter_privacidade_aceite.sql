-- Aviso de privacidade com botão [Entendi] antes do primeiro registro. Rodar uma vez no SQL Editor do Supabase.
ALTER TABLE users ADD COLUMN IF NOT EXISTS privacidade_aceita_em TIMESTAMPTZ;
