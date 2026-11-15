from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str
    api_db_user: str = "bgp_api"       # read-only login, used when api_db_password is set
    api_db_password: str = ""
    cors_origins: str = "*"            # comma-separated; "*" only for local dev
    freshness_warn_seconds: int = 180  # /health reports degraded above this
    pool_min: int = 1
    pool_max: int = 8

    @property
    def dsn(self) -> str:
        # Prefer the least-privilege account; fall back to the owner (still forced read-only below).
        user, pw = (self.api_db_user, self.api_db_password) if self.api_db_password else \
                   (self.postgres_user, self.postgres_password)
        return (f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
                f"user={user} password={pw} "
                f"application_name=bgp-api options='-c default_transaction_read_only=on'")


settings = Settings()
