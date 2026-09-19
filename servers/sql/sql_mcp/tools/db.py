import os
import re
from ..core.connection import db_pool

_PROTECTED_TABLES = frozenset(
    {
        "audit_log",
        "users",
        "sessions",
        "memberships",
        "organizations",
        "projects",
        "roles",
        "permissions",
        "role_permissions",
        "api_tokens",
        "user_invitations",
        "mfa_recovery_codes",
        "trusted_devices",
        "webauthn_credentials",
        "password_reset_tokens",
        "login_history",
        "oidc_providers",
        "host_credentials",
        "dc_credentials",
        "pg_authid",
        "pg_shadow",
        "pg_user",
        "pg_roles",
        "pg_user_mappings",
        "pg_stat_activity",
    }
)
_FORBIDDEN_IN_QUERY = (
    "insert",
    "update",
    "delete",
    "merge",
    "truncate",
    "drop",
    "alter",
    "create",
    "copy",
    "grant",
    "revoke",
    "vacuum",
    "reindex",
    "cluster",
    "comment",
    "call",
    "do",
    "set",
    "reset",
    "lock",
    "listen",
    "notify",
    "refresh",
    "prepare",
    "deallocate",
    "execute",
    "import",
    "into",
)
_DOLLAR_QUOTE_RE = re.compile("\\$(?P<tag>[A-Za-z_][A-Za-z0-9_]*)?\\$.*?\\$(?P=tag)?\\$", re.S)
_SQUOTE_RE = re.compile("'(?:[^']|'')*'")
_LINE_COMMENT_RE = re.compile("--[^\\n]*")
_BLOCK_COMMENT_RE = re.compile("/\\*.*?\\*/", re.S)


def _strip_sql_literals(sql: str) -> str:
    s = _BLOCK_COMMENT_RE.sub(" ", sql or "")
    s = _LINE_COMMENT_RE.sub(" ", s)
    s = _DOLLAR_QUOTE_RE.sub(" ", s)
    s = _SQUOTE_RE.sub(" ", s)
    return s.replace('"', " ").replace("`", " ")


def _leading_keyword(stripped: str) -> str:
    m = re.match("\\s*\\(*\\s*([A-Za-z]+)", stripped)
    return m.group(1).lower() if m else ""


def _assert_no_protected_tables(stripped: str, tool: str) -> None:
    for table in _PROTECTED_TABLES:
        if re.search(f"\\b{table}\\b", stripped, re.IGNORECASE):
            raise ValueError(
                f"{tool}: access to protected table '{table}' is not allowed through the SQL MCP (IAM/auth/audit tables are off-limits)."
            )


def _assert_readonly_query(query: str) -> None:
    stripped = _strip_sql_literals(query)
    if stripped.rstrip().rstrip(";").count(";") > 0:
        raise ValueError(
            "execute_query: semicolon-chained statements are not allowed — run exactly one SELECT."
        )
    kw = _leading_keyword(stripped)
    if kw not in ("select", "with"):
        raise ValueError(
            f"execute_query is read-only: statement starts with '{kw or '?'}' — only SELECT / WITH ... SELECT is allowed. Use execute_statement for mutations."
        )
    for word in _FORBIDDEN_IN_QUERY:
        if re.search(f"\\b{word}\\b", stripped, re.IGNORECASE):
            raise ValueError(
                f"execute_query is read-only: forbidden keyword '{word.upper()}' found in the statement."
            )
    _assert_no_protected_tables(stripped, "execute_query")


def _assert_mutate_statement(statement: str) -> None:
    stripped = _strip_sql_literals(statement)
    if stripped.rstrip().rstrip(";").count(";") > 0:
        raise ValueError(
            "execute_statement: semicolon-chained statements are not allowed — run exactly one statement."
        )
    kw = _leading_keyword(stripped)
    if kw in ("select", "with", "show", "table", "values", "explain"):
        raise ValueError(
            f"execute_statement is mutate-only: '{kw.upper()}' is a read — use execute_query instead."
        )
    _assert_no_protected_tables(stripped, "execute_statement")


_RO_SUFFIX = "__ro"


def _ro_credentials() -> "tuple[str, str] | None":
    user = os.environ.get("SQL_MCP_RO_USER", "")
    password = os.environ.get("SQL_MCP_RO_PASSWORD", "")
    if user and password:
        return (user, password)
    return None


def _ensure_ro_connection(name: str, ro_user: str, ro_password: str) -> str:
    ro_name = name + _RO_SUFFIX
    try:
        db_pool.get_pool(ro_name)
        return ro_name
    except KeyError:
        pass
    cfg = db_pool.get_config(name)
    try:
        db_pool.add_connection(ro_name, cfg.host, cfg.database, ro_user, ro_password, cfg.port)
    except Exception as e:
        raise RuntimeError(
            f"execute_query: could not connect as the read-only role '{ro_user}' (SQL_MCP_RO_USER) — refusing to fall back to the primary connection. Ensure the role exists (CREATE ROLE ... LOGIN, then GRANT CONNECT/USAGE/SELECT only) and SQL_MCP_RO_PASSWORD is correct. Underlying error: {e}"
        ) from e
    return ro_name


def connect_db(
    name: str, host: str, database: str, username: str, password: str, port: int = 5432
) -> dict:
    if not name.endswith(_RO_SUFFIX):
        db_pool.remove_connection(name + _RO_SUFFIX)
    return db_pool.add_connection(name, host, database, username, password, port)


def disconnect_db(name: str) -> dict:
    if not name.endswith(_RO_SUFFIX):
        db_pool.remove_connection(name + _RO_SUFFIX)
    return db_pool.remove_connection(name)


def list_connections() -> list:
    return db_pool.list_connections()


def test_connection(name: str) -> dict:
    try:
        result = db_pool.execute(
            name,
            "SELECT version() AS version, current_database() AS database, current_user AS user, now() AS server_time",
        )
        return {"status": "ok", "name": name, **result["rows"][0]}
    except Exception as e:
        return {"status": "error", "name": name, "error": str(e)}


def execute_query(name: str, query: str, params: list = None) -> dict:
    _assert_readonly_query(query)
    ro = _ro_credentials()
    if ro is not None:
        name = _ensure_ro_connection(name, *ro)
    return db_pool.execute(name, query, params or [], fetch=True)


def execute_statement(name: str, statement: str, params: list = None) -> dict:
    _assert_mutate_statement(statement)
    return db_pool.execute(name, statement, params or [], fetch=False)


def list_tables(name: str, schema: str = "public") -> list:
    result = db_pool.execute(
        name,
        "\n        SELECT table_name, table_type,\n               pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) AS size\n        FROM information_schema.tables\n        WHERE table_schema = %s\n        ORDER BY table_name\n    ",
        [schema],
    )
    return result["rows"]


def describe_table(name: str, table: str, schema: str = "public") -> list:
    result = db_pool.execute(
        name,
        "\n        SELECT column_name, data_type, is_nullable,\n               column_default, character_maximum_length\n        FROM information_schema.columns\n        WHERE table_schema = %s AND table_name = %s\n        ORDER BY ordinal_position\n    ",
        [schema, table],
    )
    return result["rows"]


def get_table_stats(name: str, schema: str = "public") -> list:
    result = db_pool.execute(
        name,
        "\n        SELECT relname AS table_name,\n               n_live_tup AS row_count,\n               pg_size_pretty(pg_total_relation_size(relid)) AS total_size,\n               pg_size_pretty(pg_relation_size(relid)) AS table_size\n        FROM pg_stat_user_tables\n        WHERE schemaname = %s\n        ORDER BY n_live_tup DESC\n    ",
        [schema],
    )
    return result["rows"]
