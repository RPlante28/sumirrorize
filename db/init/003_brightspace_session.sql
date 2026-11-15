-- Each person's Brightspace login, so d3l can fetch their data without them signing in every
-- time. Whoever holds these cookies is signed in as that student, so d3l encrypts them first.
CREATE TABLE brightspace_session (
    person_id    bigint PRIMARY KEY REFERENCES person ON DELETE CASCADE,
    cookies      bytea NOT NULL,
    -- when they last signed in themselves (background renewals don't change it)
    signed_in_at timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER brightspace_session_touch BEFORE UPDATE ON brightspace_session
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
