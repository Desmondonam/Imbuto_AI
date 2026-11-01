"""SQLite persistence. One file, no server: enough for one host and easy to back up."""

import hashlib
import hmac
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
create table if not exists subscribers (
    phone_hash text primary key, msisdn text, lang text, commune_id text,
    consent integer default 0, updated_at real);
create table if not exists sessions (id text primary key, state text, updated_at real);
create table if not exists predictions (
    id integer primary key, ts real, model text, version text, channel text, outcome text,
    label text, confidence real, similarity real, latency_ms real);
create table if not exists questions (
    id integer primary key, ts real, channel text, lang text, question text, source_id text,
    score real, escalated integer);
create table if not exists reports (
    id integer primary key, ts real, channel text, commune_id text, kind text);
create table if not exists feedback (
    id integer primary key, ts real, prediction_id integer, correct integer);
create table if not exists outbox (
    id integer primary key, ts real, msisdn text, body text, status text default 'queued');
create index if not exists predictions_ts on predictions (ts);
"""


class Store:
    def __init__(self, path: Path, phone_hash_key: str):
        self.path = path
        self.key = phone_hash_key.encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as con:
            con.execute("pragma journal_mode=wal")
            con.executescript(SCHEMA)

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def phone_hash(self, phone: str) -> str:
        return hmac.new(self.key, phone.encode(), hashlib.sha256).hexdigest()

    def subscriber(self, phone: str) -> dict | None:
        with self.db() as con:
            row = con.execute(
                "select * from subscribers where phone_hash = ?", (self.phone_hash(phone),)
            ).fetchone()
        return dict(row) if row else None

    def save_subscriber(self, phone: str, lang: str, commune_id: str | None) -> None:
        """The number is kept only for people who agreed, so alerts can reach them."""
        with self.db() as con:
            con.execute(
                """insert into subscribers values (?, ?, ?, ?, 1, ?)
                on conflict(phone_hash) do update set
                  msisdn = excluded.msisdn, lang = excluded.lang,
                  commune_id = coalesce(excluded.commune_id, commune_id),
                  consent = 1, updated_at = excluded.updated_at""",
                (self.phone_hash(phone), phone, lang, commune_id, time.time()),
            )

    def forget_subscriber(self, phone: str) -> None:
        with self.db() as con:
            con.execute("delete from subscribers where phone_hash = ?", (self.phone_hash(phone),))

    def load_session(self, session_id: str) -> dict:
        with self.db() as con:
            row = con.execute("select state from sessions where id = ?", (session_id,)).fetchone()
        return json.loads(row["state"]) if row else {}

    def save_session(self, session_id: str, state: dict) -> None:
        with self.db() as con:
            con.execute(
                "insert or replace into sessions values (?, ?, ?)",
                (session_id, json.dumps(state), time.time()),
            )
            con.execute("delete from sessions where updated_at < ?", (time.time() - 3600,))

    def log_prediction(self, **row) -> int:
        with self.db() as con:
            cursor = con.execute(
                """insert into predictions
                (ts, model, version, channel, outcome, label, confidence, similarity, latency_ms)
                values (:ts, :model, :version, :channel, :outcome, :label, :confidence,
                        :similarity, :latency_ms)""",
                {"ts": time.time(), **row},
            )
            return int(cursor.lastrowid)

    def log_question(self, channel, lang, question, source_id, score, escalated) -> None:
        with self.db() as con:
            con.execute(
                """insert into questions (ts, channel, lang, question, source_id, score, escalated)
                values (?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), channel, lang, question[:300], source_id, score, int(escalated)),
            )

    def log_report(self, channel: str, commune_id: str | None, kind: str) -> None:
        with self.db() as con:
            con.execute(
                "insert into reports (ts, channel, commune_id, kind) values (?, ?, ?, ?)",
                (time.time(), channel, commune_id, kind),
            )

    def log_feedback(self, prediction_id: int, correct: bool) -> None:
        with self.db() as con:
            con.execute(
                "insert into feedback (ts, prediction_id, correct) values (?, ?, ?)",
                (time.time(), prediction_id, int(correct)),
            )

    def queue_sms(self, msisdn: str, body: str) -> None:
        with self.db() as con:
            con.execute(
                "insert into outbox (ts, msisdn, body) values (?, ?, ?)",
                (time.time(), msisdn, body),
            )
