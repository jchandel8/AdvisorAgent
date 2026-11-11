-- 002: reference (lookup) tables for asset class, sector and currency, and the agent answer cache.

-- Lookup tables: securities must use one of these values (enforced by foreign keys).
CREATE TABLE asset_classes (
    code  text PRIMARY KEY,
    name  text NOT NULL
);
INSERT INTO asset_classes (code, name) VALUES
    ('equity', 'Equity'),
    ('fixed_income', 'Fixed income'),
    ('cash', 'Cash');

CREATE TABLE sectors (
    name  text PRIMARY KEY
);
INSERT INTO sectors (name) VALUES
    ('Technology'), ('Health Care'), ('Financials'), ('Consumer Discretionary'), ('Consumer Staples'),
    ('Energy'), ('Industrials'), ('Utilities'), ('Communication Services'), ('Real Estate'), ('Materials'),
    ('Fixed Income'), ('Cash');

-- ISO 4217 codes. USD only for now; other currencies would also need exchange rates for totals.
CREATE TABLE currencies (
    code  char(3) PRIMARY KEY CHECK (code = upper(code)),
    name  text NOT NULL
);
INSERT INTO currencies (code, name) VALUES ('USD', 'US dollar');

ALTER TABLE securities DROP CONSTRAINT securities_asset_class_check;
ALTER TABLE securities
    ADD CONSTRAINT securities_asset_class_fk FOREIGN KEY (asset_class) REFERENCES asset_classes(code),
    ADD CONSTRAINT securities_sector_fk FOREIGN KEY (sector) REFERENCES sectors(name),
    ADD COLUMN currency char(3) NOT NULL DEFAULT 'USD' REFERENCES currencies(code);

-- Agent answer cache. A row is a finished answer to an exact conversation, for one advisor.
-- The key is a SHA-256 over (advisor, the advisor's current account access, model, date, conversation),
-- so an access change or a new day can never reuse an old answer.
-- Eviction: rows past expires_at are ignored and deleted; above the size cap the least recently used go first.
CREATE TABLE answer_cache (
    cache_key     text PRIMARY KEY,
    advisor_id    integer NOT NULL REFERENCES advisors(id) ON DELETE CASCADE,
    model         text NOT NULL,
    answer        text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    hit_count     integer NOT NULL DEFAULT 0
);
CREATE INDEX answer_cache_expires_idx ON answer_cache (expires_at);
CREATE INDEX answer_cache_last_used_idx ON answer_cache (last_used_at);
