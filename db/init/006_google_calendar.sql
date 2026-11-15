-- Each person's Google Calendar access, so the mirror can show their events next to Brightspace's.
-- The refresh token lets whoever holds it read that person's calendar, so the app encrypts it first.
-- On an existing database run it by hand (safe to run twice):
--   docker exec -i sumirrorize-db psql -U sumirrorize < db/init/006_google_calendar.sql

CREATE TABLE IF NOT EXISTS google_calendar (
    person_id     bigint PRIMARY KEY REFERENCES person ON DELETE CASCADE,
    refresh_token bytea NOT NULL,
    connected_at  timestamptz NOT NULL DEFAULT now()
);
