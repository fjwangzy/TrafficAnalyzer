"""Use PostgreSQL kernel numbers instead of HighGo's product version banner."""
import re

from sqlalchemy.dialects.postgresql.psycopg import PGDialectAsync_psycopg


class HighGoPsycopgDialect(PGDialectAsync_psycopg):
    supports_statement_cache = True

    @classmethod
    def get_async_dialect_cls(cls, url):
        # The psycopg parent otherwise selects its original async dialect.
        return cls

    def create_connect_args(self, url):
        args, kwargs = super().create_connect_args(url)
        kwargs.pop("application_schema", None)
        return args, kwargs

    def on_connect_url(self, url):
        parent = super().on_connect_url(url)
        schema = url.query.get("application_schema", "public")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("Invalid application schema")

        def configure(connection):
            if parent:
                parent(connection)
            # Keep the session setting outside a transaction so pool rollback preserves it.
            previous = connection.autocommit
            connection.autocommit = True
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f'SET SESSION search_path TO "{schema}", public')
            finally:
                connection.autocommit = previous

        return configure

    def _get_server_version_info(self, connection):
        value = str(connection.exec_driver_sql("SHOW server_version_num").scalar_one())
        if not value.isascii() or not value.isdecimal() or int(value) < 10000:
            raise RuntimeError("HighGo must provide a valid numeric server_version_num")
        version = int(value)
        if version >= 100000:
            return version // 10000, version % 10000
        return version // 10000, version // 100 % 100, version % 100
