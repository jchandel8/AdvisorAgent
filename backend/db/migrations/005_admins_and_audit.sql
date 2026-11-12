-- 005: administrators, demo admin support, and the permission audit log (admin portal, build step 4).

CREATE TABLE admins (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username    text NOT NULL UNIQUE,
    first_name  text NOT NULL,
    last_name   text NOT NULL,
    email       text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- demo_users can now list an admin too (same exactly-one-ID pattern as account_access).
ALTER TABLE demo_users DROP CONSTRAINT demo_person_matches_type;
ALTER TABLE demo_users DROP CONSTRAINT demo_users_person_type_check;
ALTER TABLE demo_users
    ADD COLUMN admin_id integer REFERENCES admins(id) ON DELETE CASCADE,
    ADD CONSTRAINT demo_users_person_type_check CHECK (person_type IN ('advisor', 'client', 'admin')),
    ADD CONSTRAINT demo_person_matches_type CHECK (
        (person_type = 'advisor' AND advisor_id IS NOT NULL AND client_id IS NULL AND admin_id IS NULL)
        OR (person_type = 'client' AND client_id IS NOT NULL AND advisor_id IS NULL AND admin_id IS NULL)
        OR (person_type = 'admin' AND admin_id IS NOT NULL AND advisor_id IS NULL AND client_id IS NULL)
    );

-- Every change an admin makes: who, what, when. Rows are never updated or deleted by the app.
CREATE TABLE permission_audit (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    admin_id     integer REFERENCES admins(id) ON DELETE SET NULL,
    admin_name   text NOT NULL,                 -- kept even if the admin is later removed
    action       text NOT NULL CHECK (action IN ('grant', 'revoke', 'create_user', 'create_account')),
    account_id   integer REFERENCES accounts(id) ON DELETE SET NULL,
    person_type  text CHECK (person_type IN ('advisor', 'client', 'admin')),
    person_id    integer,
    role         text,
    summary      text NOT NULL                  -- plain-language description for the log screen
);
CREATE INDEX permission_audit_time_idx ON permission_audit (created_at DESC);
