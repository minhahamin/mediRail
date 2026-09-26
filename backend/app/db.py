"""SQLite 스키마와 연결 헬퍼."""
import sqlite3
from pathlib import Path

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, birth_year INTEGER, sex TEXT,
  allergies TEXT DEFAULT '', medications TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('patient','doctor','nurse','admin')),
  name TEXT NOT NULL, patient_id INTEGER REFERENCES patients(id)
);
CREATE TABLE IF NOT EXISTS intakes (
  id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
  text TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS encounters (
  id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
  doctor_id INTEGER NOT NULL REFERENCES users(id), visit_date TEXT NOT NULL,
  chief_complaint TEXT NOT NULL, notes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
  doctor_id INTEGER NOT NULL REFERENCES users(id), slot TEXT NOT NULL, reason TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','cancelled')), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS soap_notes (
  id INTEGER PRIMARY KEY, encounter_id INTEGER NOT NULL REFERENCES encounters(id),
  subjective TEXT, objective TEXT, assessment TEXT, plan TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved')),
  created_by INTEGER REFERENCES users(id), approved_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, user_id INTEGER, role TEXT, action TEXT NOT NULL, detail TEXT
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or get_settings().db_path
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def get_db():
    """FastAPI 의존성: 요청마다 연결을 열고 닫는다."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
