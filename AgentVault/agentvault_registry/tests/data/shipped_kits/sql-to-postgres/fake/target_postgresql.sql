-- The new table on PostgreSQL. The migration's login needs INSERT, UPDATE, SELECT and DELETE on it, nothing else:
--   GRANT INSERT, UPDATE, SELECT, DELETE ON public.customers TO tp_migrate;
CREATE TABLE IF NOT EXISTS public.customers (
    legacy_id  integer PRIMARY KEY,
    full_name  text NOT NULL,
    email      text,
    signed_up  date NOT NULL,
    status     text NOT NULL CHECK (status IN ('active', 'inactive', 'blocked'))
);
