-- 001_schema.sql: core tables for the wealth-advisor project.
-- Conventions: snake_case, identity integer PKs, every link is a real foreign key,
-- derived values (market value, weights, client counts) are computed in queries, not stored.

CREATE TABLE advisors (
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username        text NOT NULL UNIQUE,
    first_name      text NOT NULL,
    last_name       text NOT NULL,
    email           text NOT NULL UNIQUE,
    phone           text,
    certifications  text[] NOT NULL DEFAULT '{}',
    city            text,
    state           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE clients (
    id                 integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username           text NOT NULL UNIQUE,
    first_name         text NOT NULL,
    last_name          text NOT NULL,
    email              text NOT NULL UNIQUE,
    phone              text,
    address            text,
    city               text,
    state              text,
    risk_profile       text NOT NULL
        CHECK (risk_profile IN ('conservative', 'moderate', 'growth', 'aggressive')),
    target_allocation  jsonb NOT NULL CHECK (jsonb_typeof(target_allocation) = 'object'),
    next_review_date   date,
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE accounts (
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_name  text NOT NULL,
    account_type  text NOT NULL CHECK (account_type IN ('individual', 'joint', 'ira', 'trust')),
    description   text,
    open_date     date NOT NULL,
    close_date    date,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CHECK (close_date IS NULL OR close_date >= open_date)
);

-- The ACL. One row = one person's access to one account.
-- Exactly one of advisor_id / client_id is set, and it must match person_type,
-- so both columns can be real foreign keys.
CREATE TABLE account_access (
    id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id   integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    person_type  text NOT NULL CHECK (person_type IN ('advisor', 'client')),
    advisor_id   integer REFERENCES advisors(id) ON DELETE CASCADE,
    client_id    integer REFERENCES clients(id) ON DELETE CASCADE,
    role         text NOT NULL,
    granted_at   timestamptz NOT NULL DEFAULT now(),
    granted_by   text,  -- who granted it; used by the admin audit log (build step 4)
    CONSTRAINT access_person_matches_type CHECK (
        (person_type = 'advisor' AND advisor_id IS NOT NULL AND client_id IS NULL)
        OR (person_type = 'client' AND client_id IS NOT NULL AND advisor_id IS NULL)
    ),
    CONSTRAINT access_role_matches_type CHECK (
        (person_type = 'advisor' AND role IN ('advisor', 'viewer'))
        OR (person_type = 'client' AND role IN ('owner', 'joint_owner', 'viewer'))
    )
);
CREATE UNIQUE INDEX account_access_advisor_uq ON account_access (advisor_id, account_id)
    WHERE advisor_id IS NOT NULL;
CREATE UNIQUE INDEX account_access_client_uq ON account_access (client_id, account_id)
    WHERE client_id IS NOT NULL;
CREATE INDEX account_access_account_idx ON account_access (account_id);

-- Read-only view in the (person_type, person_id) shape described in CLAUDE.md.
CREATE VIEW v_account_access AS
SELECT account_id, person_type, COALESCE(advisor_id, client_id) AS person_id, role, granted_at, granted_by
FROM account_access;

CREATE TABLE securities (
    symbol       text PRIMARY KEY,
    description  text NOT NULL,
    sector       text NOT NULL,
    asset_class  text NOT NULL CHECK (asset_class IN ('equity', 'fixed_income', 'cash'))
);

-- Position snapshots: one row per account, symbol and as_of_date (month ends plus the latest date).
-- cost_basis is the TOTAL cost of the position (average cost method), not per share.
CREATE TABLE holdings (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id  integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol      text NOT NULL REFERENCES securities(symbol),
    quantity    numeric(16,4) NOT NULL CHECK (quantity > 0),
    cost_basis  numeric(16,2) NOT NULL CHECK (cost_basis >= 0),
    price       numeric(14,4) NOT NULL CHECK (price > 0),
    as_of_date  date NOT NULL,
    UNIQUE (account_id, as_of_date, symbol)
);

-- amount is always a positive dollar figure; the type says which way cash moved.
-- realized_gain is recorded on sells at trade time (average cost), like a broker trade confirm.
CREATE TABLE transactions (
    id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id     integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    trade_date     date NOT NULL,
    type           text NOT NULL CHECK (type IN ('buy', 'sell', 'dividend', 'deposit', 'withdrawal')),
    symbol         text REFERENCES securities(symbol),
    quantity       numeric(16,4),
    price          numeric(14,4),
    amount         numeric(16,2) NOT NULL CHECK (amount >= 0),
    realized_gain  numeric(16,2),
    CONSTRAINT txn_shape CHECK (
        (type IN ('buy', 'sell') AND symbol IS NOT NULL AND quantity > 0 AND price > 0)
        OR (type = 'dividend' AND symbol IS NOT NULL AND quantity IS NULL)
        OR (type IN ('deposit', 'withdrawal') AND symbol IS NULL AND quantity IS NULL)
    ),
    CONSTRAINT txn_realized_only_on_sell CHECK (realized_gain IS NULL OR type = 'sell')
);
CREATE INDEX transactions_account_date_idx ON transactions (account_id, trade_date);

-- Returns are fractions (0.0523 = 5.23%). NULL when the account is younger than the period.
CREATE TABLE performance (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id  integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    as_of_date  date NOT NULL,
    return_1d   numeric(10,6),
    return_1m   numeric(10,6),
    return_3m   numeric(10,6),
    return_6m   numeric(10,6),
    return_ytd  numeric(10,6),
    return_1y   numeric(10,6),
    return_2y   numeric(10,6),
    return_3y   numeric(10,6),
    return_5y   numeric(10,6),
    UNIQUE (account_id, as_of_date)
);

CREATE TABLE documents (
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id    integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    title         text NOT NULL,
    doc_type      text NOT NULL CHECK (doc_type IN ('ips', 'review_notes', 'statement', 'agreement')),
    text          text NOT NULL,
    size_kb       integer NOT NULL CHECK (size_kb > 0),
    created_date  date NOT NULL
);
CREATE INDEX documents_account_idx ON documents (account_id);
