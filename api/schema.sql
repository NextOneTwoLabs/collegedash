-- D1 schema for the /api/v1 gate (issue #345). Applied once by the owner:
--   npx wrangler d1 execute collegedash-api --remote --file api/schema.sql
-- Safe to re-run. No key value is ever stored: `hash` is the SHA-256 (hex) of the full key.

CREATE TABLE IF NOT EXISTS keys (
  id      TEXT PRIMARY KEY,                    -- the 12-character key id, not secret (cdk_<id>_<secret>)
  hash    TEXT NOT NULL UNIQUE,                -- sha256(full key), hex
  label   TEXT NOT NULL,                       -- who the key is for
  created TEXT NOT NULL,                       -- ISO date-time, UTC
  status  TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
  quota   INTEGER NOT NULL CHECK (quota >= 1)  -- requests per UTC day; a customer with no allowance is revoked, not 0
);

CREATE TABLE IF NOT EXISTS usage (
  key_id TEXT NOT NULL REFERENCES keys (id),
  day    TEXT NOT NULL,                        -- YYYY-MM-DD, UTC
  count  INTEGER NOT NULL,                     -- served requests only; a refused one is never counted
  PRIMARY KEY (key_id, day)
);
