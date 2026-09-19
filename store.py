"""Storage for the portal: SQLite by default, PostgreSQL when DATABASE_URL is set.

Why both. On an office PC or a VM the portal keeps using `portal.db` next to the
code, exactly as before — nothing to set up. On a free cloud host the disk is
wiped every time the service restarts or redeploys, so a SQLite file there would
lose the day's entries; pointing DATABASE_URL at a free managed Postgres keeps
the data instead. The rest of the app does not care which one is in use.

All SQL in the app is written with `?` placeholders and translated for Postgres
here. Column names avoid `user`, `by` and `at`, which Postgres reserves.
"""
import os, re, sqlite3, threading, time
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))

DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, name TEXT, salt TEXT, hash TEXT, admin INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER, doc TEXT, saved_by TEXT, saved_at TEXT);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT, at_ts TEXT, username TEXT, version INTEGER, changes TEXT);
CREATE TABLE IF NOT EXISTS snapshots(version INTEGER PRIMARY KEY, at_ts TEXT, username TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS ai_usage(day TEXT PRIMARY KEY, n INTEGER);
"""
DDL_PG = """
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, name TEXT, salt TEXT, hash TEXT, admin INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER, doc TEXT, saved_by TEXT, saved_at TEXT);
CREATE TABLE IF NOT EXISTS log(id BIGSERIAL PRIMARY KEY, at_ts TEXT, username TEXT, version INTEGER, changes TEXT);
CREATE TABLE IF NOT EXISTS snapshots(version INTEGER PRIMARY KEY, at_ts TEXT, username TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS ai_usage(day TEXT PRIMARY KEY, n INTEGER);
"""

_local = threading.local()


class Cur:
    """A cursor that speaks `?` placeholders and returns plain dicts."""

    def __init__(self, cur, kind):
        self.cur, self.kind = cur, kind

    @property
    def for_update(self):
        """Append to a SELECT that a write in the same transaction depends on.

        Postgres takes a row lock, so a second saver waits and then reads the row the
        first one just wrote — and reports an honest version conflict instead of
        colliding further down. SQLite needs nothing here: its whole write
        transaction is already exclusive (see `txn(write=True)`)."""
        return " FOR UPDATE" if self.kind == "postgres" else ""

    def _sql(self, sql):
        return re.sub(r"\?", "%s", sql) if self.kind == "postgres" else sql

    def run(self, sql, params=()):
        self.cur.execute(self._sql(sql), tuple(params))
        return self

    def _cols(self):
        return [d[0] for d in (self.cur.description or [])]

    def one(self, sql, params=()):
        self.run(sql, params)
        r = self.cur.fetchone()
        return dict(zip(self._cols(), r)) if r else None

    def all(self, sql, params=()):
        self.run(sql, params)
        cols = self._cols()
        return [dict(zip(cols, r)) for r in self.cur.fetchall()]


class Store:
    def __init__(self, url=None, path=None):
        self.url = (url if url is not None else os.environ.get("DATABASE_URL", "")).strip()
        self.kind = "postgres" if self.url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self.path = path or os.environ.get("DB_PATH") or os.path.join(HERE, "portal.db")
        if self.kind == "postgres":
            import psycopg  # fails early and loudly if the driver is missing
            self._psycopg = psycopg
            # psycopg 3 wants the postgresql:// spelling
            if self.url.startswith("postgres://"):
                self.url = "postgresql://" + self.url[len("postgres://"):]

    # ---------- connections ----------
    def _connect(self):
        if self.kind == "postgres":
            return self._psycopg.connect(self.url, autocommit=False, connect_timeout=15)
        # isolation_level=None: no transaction is started behind our back, so txn()
        # below decides when a write transaction begins and how exclusive it is.
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")       # a reader never blocks the person saving
        c.execute("PRAGMA busy_timeout=10000")
        return c

    def _live(self):
        """One connection per thread for Postgres; a fresh one each time for SQLite.

        A managed Postgres on a free plan drops idle connections, so the cached one
        is tested before reuse and quietly replaced when it has gone away.
        """
        if self.kind == "sqlite":
            return self._connect(), True
        c = getattr(_local, "conn", None)
        if c is not None:
            try:
                c.execute("SELECT 1")
                c.rollback()
                return c, False
            except Exception:
                try: c.close()
                except Exception: pass
                _local.conn = None
        _local.conn = self._connect()
        return _local.conn, False

    @contextmanager
    def txn(self, write=False):
        """Everything inside commits together, or none of it does.

        `write=True` marks a transaction that reads a row and then writes it. On
        SQLite it begins immediately, so two people saving in the same instant are
        serialised rather than both believing they hold the current version.
        """
        conn, disposable = self._live()
        cur = conn.cursor()
        try:
            if self.kind == "sqlite":
                cur.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield Cur(cur, self.kind)
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
            raise
        finally:
            try: cur.close()
            except Exception: pass
            if disposable:
                conn.close()

    # ---------- one-liners ----------
    def one(self, sql, params=()):
        with self.txn() as c:
            return c.one(sql, params)

    # `write=True` on the one-liners too, so a lone INSERT/UPDATE takes the same lock

    def all(self, sql, params=()):
        with self.txn() as c:
            return c.all(sql, params)

    def run(self, sql, params=()):
        with self.txn(write=True) as c:
            c.run(sql, params)

    # ---------- schema ----------
    def init(self):
        """Create anything missing. Safe to call from several workers at once:
        `CREATE TABLE IF NOT EXISTS` can still collide when two of them run it in
        the same instant, so a collision is simply retried."""
        if self.kind == "sqlite":
            self._migrate_sqlite()
        stmts = [x for x in (DDL_PG if self.kind == "postgres" else DDL_SQLITE).strip().split(";\n") if x.strip()]
        for attempt in (1, 2, 3):
            try:
                with self.txn(write=True) as c:
                    for stmt in stmts:
                        c.run(stmt)
                return
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(0.5 * attempt)

    def _migrate_sqlite(self):
        """Carry a portal.db written by the first version of the server forward.

        That schema used `users.user`, `state.json/by/at`, `log.user/at` and
        `snapshots.user/at` — all fine in SQLite, all reserved words in Postgres.
        The tables are renamed and copied once; a database already on the new
        schema, or a brand-new one, is left alone.
        """
        if not os.path.exists(self.path):
            return
        c = sqlite3.connect(self.path, timeout=30)
        try:
            cols = lambda t: [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
            if "user" not in cols("users"):
                return
            c.executescript("""
            ALTER TABLE users RENAME TO users_old;
            ALTER TABLE state RENAME TO state_old;
            ALTER TABLE log RENAME TO log_old;
            ALTER TABLE snapshots RENAME TO snapshots_old;
            """)
            c.executescript(DDL_SQLITE)
            c.executescript("""
            INSERT INTO users(username,name,salt,hash,admin) SELECT user,name,salt,hash,admin FROM users_old;
            INSERT INTO state(id,version,doc,saved_by,saved_at) SELECT id,version,json,by,at FROM state_old;
            INSERT INTO log(at_ts,username,version,changes) SELECT at,user,version,changes FROM log_old;
            INSERT INTO snapshots(version,at_ts,username,doc) SELECT version,at,user,json FROM snapshots_old;
            DROP TABLE users_old; DROP TABLE state_old; DROP TABLE log_old; DROP TABLE snapshots_old;
            """)
            c.commit()
        finally:
            c.close()

    def describe(self):
        return f"PostgreSQL ({self.url.split('@')[-1].split('/')[0]})" if self.kind == "postgres" else f"SQLite ({self.path})"
