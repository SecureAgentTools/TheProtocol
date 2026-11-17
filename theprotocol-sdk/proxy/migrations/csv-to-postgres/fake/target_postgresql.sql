-- The new table on PostgreSQL. The migration's login needs INSERT, UPDATE, SELECT and DELETE on it, nothing else:
--   GRANT INSERT, UPDATE, SELECT, DELETE ON public.orders TO tp_migrate;
CREATE TABLE IF NOT EXISTS public.orders (
    order_no     bigint PRIMARY KEY,
    customer_id  integer NOT NULL,
    ordered_at   timestamptz NOT NULL,
    amount       numeric(12, 2) NOT NULL,
    currency     char(3) NOT NULL,
    status       text NOT NULL
);
