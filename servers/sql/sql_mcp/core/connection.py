import logging
import threading
from dataclasses import dataclass
import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)


@dataclass
class DBConfig:
    name: str
    host: str
    port: int
    database: str
    username: str
    password: str


class DBPool:

    def __init__(self):
        self._lock = threading.Lock()
        self._configs: dict[str, DBConfig] = {}
        self._pools: dict[str, psycopg2.pool.ThreadedConnectionPool] = {}

    def add_connection(
        self, name: str, host: str, database: str, username: str, password: str, port: int = 5432
    ) -> dict:
        cfg = DBConfig(
            name=name, host=host, port=port, database=database, username=username, password=password
        )
        with self._lock:
            if name in self._pools:
                try:
                    self._pools[name].closeall()
                except Exception:
                    pass
            pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                host=cfg.host,
                port=cfg.port,
                dbname=cfg.database,
                user=cfg.username,
                password=cfg.password,
                connect_timeout=10,
            )
            self._configs[name] = cfg
            self._pools[name] = pool
        logger.info("Connected to DB '%s' at %s:%s/%s", name, host, port, database)
        return {"status": "ok", "name": name, "host": host, "database": database, "port": port}

    def remove_connection(self, name: str) -> dict:
        with self._lock:
            pool = self._pools.pop(name, None)
            if pool:
                try:
                    pool.closeall()
                except Exception:
                    pass
            self._configs.pop(name, None)
        return {"status": "ok", "name": name, "message": "disconnected"}

    def list_connections(self) -> list:
        with self._lock:
            return [
                {
                    "name": c.name,
                    "host": c.host,
                    "port": c.port,
                    "database": c.database,
                    "username": c.username,
                }
                for c in self._configs.values()
            ]

    def get_pool(self, name: str) -> psycopg2.pool.ThreadedConnectionPool:
        with self._lock:
            pool = self._pools.get(name)
        if not pool:
            raise KeyError(f"No connection '{name}'. Call connect_db first.")
        return pool

    def get_config(self, name: str) -> DBConfig:
        with self._lock:
            cfg = self._configs.get(name)
        if not cfg:
            raise KeyError(f"No connection '{name}'. Call connect_db first.")
        return cfg

    def execute(self, name: str, query: str, params=None, fetch: bool = True) -> dict:
        pool = self.get_pool(name)
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch and cur.description:
                    rows = [dict(r) for r in cur.fetchall()]
                    conn.commit()
                    return {"rows": rows, "count": len(rows)}
                else:
                    conn.commit()
                    return {"rows": [], "count": cur.rowcount, "affected": cur.rowcount}
        except Exception as e:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)


db_pool = DBPool()
