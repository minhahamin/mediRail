"""DB 연결. 개발·테스트는 SQLite, 배포는 PostgreSQL(DATABASE_URL).

서비스 계층은 sqlite3 스타일 API(`conn.execute(sql, params)`, `?` 자리표시자, `cursor.lastrowid`,
이름·인덱스 둘 다 되는 Row)만 사용한다. PostgreSQL 연결은 이 인터페이스를 흉내 내는 얇은 어댑터로 감싸서
서비스 코드를 바꾸지 않고 두 DB에서 같은 테스트를 돌린다.
"""
import re
import sqlite3
from pathlib import Path

from .config import get_settings

# {PK}: SQLite는 INTEGER PRIMARY KEY(자동 증가), PostgreSQL은 SERIAL PRIMARY KEY
SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
  id {PK}, name TEXT NOT NULL, birth_year INTEGER, sex TEXT,
  allergies TEXT DEFAULT '', medications TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
  id {PK}, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('patient','doctor','nurse','admin','superadmin')),
  name TEXT NOT NULL, patient_id INTEGER REFERENCES patients(id),
  read_only INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS intakes (
  id {PK}, patient_id INTEGER NOT NULL REFERENCES patients(id),
  text TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS encounters (
  id {PK}, patient_id INTEGER NOT NULL REFERENCES patients(id),
  doctor_id INTEGER NOT NULL REFERENCES users(id), visit_date TEXT NOT NULL,
  chief_complaint TEXT NOT NULL, notes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
  id {PK}, patient_id INTEGER NOT NULL REFERENCES patients(id),
  doctor_id INTEGER NOT NULL REFERENCES users(id), slot TEXT NOT NULL, reason TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','cancelled')), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS soap_notes (
  id {PK}, encounter_id INTEGER NOT NULL REFERENCES encounters(id),
  subjective TEXT, objective TEXT, assessment TEXT, plan TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved')),
  created_by INTEGER REFERENCES users(id), approved_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id {PK}, ts TEXT NOT NULL, user_id INTEGER, role TEXT, action TEXT NOT NULL, detail TEXT
);
"""

_PG_PREFIXES = ("postgres://", "postgresql://")


class Row(tuple):
    """이름과 인덱스로 모두 접근되는 행 (sqlite3.Row와 같은 사용법). dict(row)도 된다."""

    def __new__(cls, names, values):
        obj = super().__new__(cls, values)
        obj._names = list(names)
        return obj

    def __getitem__(self, key):
        return super().__getitem__(self._names.index(key)) if isinstance(key, str) else super().__getitem__(key)

    def keys(self):
        return list(self._names)


def _row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Row(names, values)


class PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur, self.lastrowid = cur, lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)


class PgConnection:
    """psycopg 연결을 sqlite3 스타일로 감싼다: ?→%s, INSERT 시 RETURNING id로 lastrowid 제공."""

    def __init__(self, dsn: str):
        import psycopg  # 배포(PostgreSQL)에서만 필요

        self._c = psycopg.connect(dsn, row_factory=_row_factory)

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("%", "%%").replace("?", "%s")

    def execute(self, sql: str, params=()):
        sql = self._sql(sql)
        insert = bool(re.match(r"\s*INSERT\s+INTO", sql, re.I)) and "RETURNING" not in sql.upper()
        cur = self._c.execute(sql + (" RETURNING id" if insert else ""), params)
        if insert:
            row = cur.fetchone()
            return PgCursor(cur, row[0] if row else None)
        return PgCursor(cur)

    def executemany(self, sql: str, seq):
        with self._c.cursor() as cur:
            cur.executemany(self._sql(sql), list(seq))

    def executescript(self, script: str):
        for stmt in script.split(";"):
            if stmt.strip():
                self._c.execute(stmt)
        self._c.commit()

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()


def is_postgres(conn) -> bool:
    return isinstance(conn, PgConnection)


def connect(target: str | None = None):
    s = get_settings()
    target = target or s.database_url or s.db_path
    if str(target).startswith(_PG_PREFIXES):
        return PgConnection(target)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


ROLE_CHECK = "CHECK (role IN ('patient','doctor','nurse','admin','superadmin'))"


def init_db(conn) -> None:
    schema = SCHEMA.replace("{PK}", "SERIAL PRIMARY KEY" if is_postgres(conn) else "INTEGER PRIMARY KEY")
    conn.executescript(schema)
    conn.commit()
    migrate(conn)


def migrate(conn) -> None:
    """이미 배포된 DB를 데이터 손실 없이 최신 스키마로 올린다 (멱등). users에 read_only/disabled 컬럼을 더하고 role 제약에 superadmin을 허용한다."""
    if is_postgres(conn):
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS read_only INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
        conn.execute(f"ALTER TABLE users ADD CONSTRAINT users_role_check {ROLE_CHECK}")
        conn.commit()
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
    if "superadmin" in ddl and {"read_only", "disabled"} <= cols:
        return
    # SQLite는 CHECK 제약을 바꿀 수 없어 테이블을 다시 만들며 데이터를 옮긴다 (FK는 잠시 끈다)
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA legacy_alter_table=ON")
    conn.execute("ALTER TABLE users RENAME TO users_old")
    conn.executescript(SCHEMA_USERS_SQLITE)
    keep = ", ".join(c for c in ("id", "username", "password_hash", "role", "name", "patient_id", "read_only", "disabled") if c in cols)
    conn.execute(f"INSERT INTO users ({keep}) SELECT {keep} FROM users_old")
    conn.execute("DROP TABLE users_old")
    conn.execute("PRAGMA legacy_alter_table=OFF")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()


SCHEMA_USERS_SQLITE = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('patient','doctor','nurse','admin','superadmin')),
  name TEXT NOT NULL, patient_id INTEGER REFERENCES patients(id),
  read_only INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0
);
"""


def resync_sequences(conn) -> None:
    """시드가 id를 직접 넣은 테이블은 PostgreSQL 시퀀스를 맞춰야 다음 INSERT가 충돌하지 않는다."""
    if not is_postgres(conn):
        return
    for table in ("patients", "users"):
        conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))")
    conn.commit()


def get_db():
    """FastAPI 의존성: 요청마다 연결을 열고 닫는다."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
