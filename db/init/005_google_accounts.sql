-- Links a person to the Google account they sign in with.
-- On an existing database run it by hand (safe to run twice):
--   docker exec -i sumirrorize-db psql -U sumirrorize < db/init/005_google_accounts.sql

-- Google's ID for the account (the `sub` claim). It never changes, even if their name or email
-- does. NULL for people added by hand before the app existed.
ALTER TABLE person ADD COLUMN IF NOT EXISTS google_sub text UNIQUE CHECK (google_sub <> '');
