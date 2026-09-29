import sqlite3
from contextlib import closing
from datetime import datetime


class ConversationManager:
    """Manages named conversation sessions."""

    def __init__(self, db_path="conversation_history.db"):
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self):
        """Open a connection that is closed when the `with` block ends."""
        return closing(sqlite3.connect(self.db_path))

    def _init_db(self):
        with self._connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    tags TEXT,
                    created_at TIMESTAMP
                )
            ''')
            conn.commit()

    def create_session(self, name, tags=""):
        """Create a session and return its ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                'INSERT INTO sessions (name, tags, created_at) VALUES (?, ?, ?)',
                (name, tags, datetime.now().isoformat())
            )
            conn.commit()
            return cursor.lastrowid

    def get_all_sessions(self):
        """Return all sessions, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT id, name, tags, created_at FROM sessions ORDER BY id DESC'
            ).fetchall()
        return [{"id": i, "name": n, "tags": t, "created_at": c} for i, n, t, c in rows]

    def update_session_name(self, session_id, new_name):
        """Rename a session. Returns False if it doesn't exist."""
        with self._connect() as conn:
            cursor = conn.execute('UPDATE sessions SET name = ? WHERE id = ?', (new_name, session_id))
            conn.commit()
            return cursor.rowcount > 0

    def delete_session(self, session_id):
        """Delete a session. Returns False if it doesn't exist."""
        with self._connect() as conn:
            cursor = conn.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
            conn.commit()
            return cursor.rowcount > 0
