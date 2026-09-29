import os

DB_PATH = os.getenv("DB_PATH", ":memory:")
KONG_ADMIN_URL = os.getenv("KONG_ADMIN_URL", "http://kong:8001")
KONG_CONFIG_PATH = os.getenv("KONG_CONFIG_PATH", "")  # where Kong reads kong.yml; empty = don't write
USAGE_INGEST_URL = os.getenv("USAGE_INGEST_URL", "http://usage-ingest:8100")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me-please-32b!")
AUTO_SYNC = os.getenv("AUTO_SYNC", "false").lower() == "true"
