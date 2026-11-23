"""Durable farming sessions with verified meso and optional fragment counts."""
from contextlib import contextmanager
from datetime import datetime, date, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from PySide6.QtCore import QStandardPaths

KST = timezone(timedelta(hours=9))
MAX_BALANCE = 2**63 - 1


def fragment_total(sessions):
    changes = [row['fragment_change'] for row in sessions if row['fragment_change'] is not None]
    return sum(changes) if changes else None


def farming_root():
    return Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / 'DesktopShimeji' / 'Farming'


class FarmingStore:
    SESSION_SCHEMA = '''(
        id TEXT PRIMARY KEY, status TEXT NOT NULL, character_id TEXT NOT NULL,
        started_at TEXT NOT NULL, ended_at TEXT, start_meso INTEGER NOT NULL,
        start_fragments INTEGER, end_meso INTEGER, end_fragments INTEGER,
        start_evidence TEXT NOT NULL, end_evidence TEXT, note TEXT NOT NULL)'''

    def __init__(self, path=None, clock=None):
        self.path = Path(path) if path is not None else farming_root() / 'records.sqlite3'
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @contextmanager
    def database(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS sessions ' + self.SESSION_SCHEMA)
            legacy = "SELECT 1 FROM pragma_table_info('sessions') WHERE name='start_fragments' AND [notnull]=1"
            if connection.execute(legacy).fetchone():
                connection.execute('BEGIN IMMEDIATE')
                if connection.execute(legacy).fetchone():
                    connection.execute('ALTER TABLE sessions RENAME TO legacy_sessions')
                    connection.execute('CREATE TABLE sessions ' + self.SESSION_SCHEMA)
                    connection.execute('INSERT INTO sessions SELECT * FROM legacy_sessions')
                    connection.execute('DROP TABLE legacy_sessions')
                connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON sessions(status) WHERE status = 'active'")
                connection.commit()
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON sessions(status) WHERE status = 'active'")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def validate_snapshot(snapshot):
        meso, fragments = snapshot.get('meso'), snapshot.get('fragments')
        if type(meso) is not int or not 0 <= meso <= MAX_BALANCE:
            raise ValueError('메소를 확실하게 판독해야 기록할 수 있습니다.')
        if fragments is not None and (type(fragments) is not int or not 0 <= fragments <= MAX_BALANCE):
            raise ValueError('솔 에르다 조각 수량이 올바르지 않습니다.')

    def describe(self, row):
        if row is None:
            return None
        result = dict(row)
        for key in ('start_evidence', 'end_evidence'):
            result.pop(key, None)
        start = datetime.fromisoformat(result['started_at'])
        end = datetime.fromisoformat(result['ended_at']) if result['ended_at'] else self.clock()
        result['duration_seconds'] = max(0, int((end - start).total_seconds()))
        if result['status'] == 'completed':
            result['meso_change'] = result['end_meso'] - result['start_meso']
            start_fragments, end_fragments = result['start_fragments'], result['end_fragments']
            result['fragment_change'] = (end_fragments - start_fragments
                                         if start_fragments is not None and end_fragments is not None else None)
            seconds = result['duration_seconds']
            result['meso_per_hour'] = round(result['meso_change'] * 3600 / seconds) if seconds else None
        result['started_at'] = start.astimezone(KST).isoformat()
        result['ended_at'] = end.astimezone(KST).isoformat() if result['ended_at'] else None
        return result

    def active(self):
        with self.database() as db:
            return self.describe(db.execute("SELECT * FROM sessions WHERE status='active'").fetchone())

    def start(self, snapshot, character_id='', note=''):
        self.validate_snapshot(snapshot)
        now = self.clock().astimezone(timezone.utc).isoformat()
        identifier = uuid.uuid4().hex
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute("SELECT * FROM sessions WHERE status='active'").fetchone()
            if active:
                return {'status': 'already_active', 'session': self.describe(active)}
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (
                identifier, 'active', character_id, now, None, snapshot['meso'], snapshot.get('fragments'),
                None, None, json.dumps(snapshot, ensure_ascii=False), None, note))
            return {'status': 'started', 'session': self.describe(db.execute('SELECT * FROM sessions WHERE id=?', (identifier,)).fetchone())}

    def finish(self, session_id, snapshot):
        self.validate_snapshot(snapshot)
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
            if row is None or row['status'] != 'active':
                return {'status': 'not_active', 'session': self.describe(row)}
            now = self.clock().astimezone(timezone.utc)
            if now < datetime.fromisoformat(row['started_at']):
                raise ValueError('PC 시간이 시작 시각보다 이전입니다. 시간을 확인해주세요.')
            db.execute("UPDATE sessions SET status='completed',ended_at=?,end_meso=?,end_fragments=?,end_evidence=? WHERE id=?", (
                now.isoformat(), snapshot['meso'], snapshot.get('fragments'), json.dumps(snapshot, ensure_ascii=False), session_id))
            return {'status': 'completed', 'session': self.describe(db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone())}

    def cancel(self, session_id):
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE sessions SET status='cancelled', ended_at=? WHERE id=? AND status='active'", (
                self.clock().astimezone(timezone.utc).isoformat(), session_id)).rowcount
            return {'status': 'cancelled' if changed else 'not_active'}

    def delete_completed(self, session_ids):
        if not isinstance(session_ids, (list, tuple)) or any(not isinstance(identifier, str) or not identifier for identifier in session_ids):
            raise ValueError('삭제할 기록 ID가 올바르지 않습니다.')
        identifiers = list(dict.fromkeys(session_ids))
        if not identifiers:
            return 0
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            count = 0
            for identifier in identifiers:
                count += db.execute("DELETE FROM sessions WHERE id=? AND status='completed'", (identifier,)).rowcount
            return count

    def query(self, since=None, until=None, limit=None):
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError('조회 개수는 양의 정수여야 합니다.')
        clauses, values = ["status='completed'"], []
        if since:
            clauses.append('ended_at >= ?')
            values.append(datetime.combine(date.fromisoformat(since), time(), KST).astimezone(timezone.utc).isoformat())
        if until:
            clauses.append('ended_at < ?')
            values.append(datetime.combine(date.fromisoformat(until) + timedelta(days=1), time(), KST).astimezone(timezone.utc).isoformat())
        if since and until and date.fromisoformat(since) > date.fromisoformat(until):
            raise ValueError('조회 시작일이 종료일보다 늦습니다.')
        with self.database() as db:
            rows = db.execute('SELECT * FROM sessions WHERE ' + ' AND '.join(clauses) + ' ORDER BY ended_at DESC', values).fetchall()
            sessions = [self.describe(row) for row in rows]
            return {'status': 'ok', 'timezone': 'Asia/Seoul', 'since': since, 'until': until,
                    'completed_sessions': len(sessions), 'total_seconds': sum(row['duration_seconds'] for row in sessions),
                    'meso_change': sum(row['meso_change'] for row in sessions),
                    'fragment_change': fragment_total(sessions),
                    'sessions': sessions if limit is None else sessions[:limit],
                    'has_more': limit is not None and len(sessions) > limit, 'active': self.active()}
