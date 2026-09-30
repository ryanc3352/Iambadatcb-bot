import sqlite3
from contextlib import closing
from pathlib import Path


TITLE_CHARS = 60


def automatic_title(first_question):
    """A chat's title from its first question, on one short line."""
    title = " ".join((first_question or "").split())
    if not title:
        return "New chat"
    return title if len(title) <= TITLE_CHARS else title[:TITLE_CHARS - 1].rstrip() + "…"


class ConversationHistory:
    """User and assistant messages in SQLite, grouped into chats. Only the current chat is used as context."""

    # Older versions started a new conversation with this marker row instead of a chat id
    MARKER_ROLE = 'System'
    NEW_CONVERSATION = '--- new conversation ---'

    def __init__(self, db_path="conversation_history.db"):
        """Open (or create) the database file at `db_path`."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_table()

    def _connect(self):
        """Open a connection that is closed when the `with` block ends."""
        return closing(sqlite3.connect(str(self.db_path)))

    def create_table(self):
        """Create the tables if needed."""
        with self._connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # `opened` orders chats by when they were last opened: the highest is the current chat
            conn.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    created DATETIME DEFAULT CURRENT_TIMESTAMP,
                    opened INTEGER NOT NULL DEFAULT 0
                )
            ''')
            columns = [row[1] for row in conn.execute('PRAGMA table_info(conversation_history)')]
            if 'conversation_id' not in columns:
                conn.execute('ALTER TABLE conversation_history ADD COLUMN conversation_id INTEGER')
            conn.execute('CREATE INDEX IF NOT EXISTS history_by_chat ON conversation_history (conversation_id)')
            self._sort_old_messages(conn)
            conn.commit()

    def _sort_old_messages(self, conn):
        """Put messages from older versions (no chat id) into chats, split at the marker rows."""
        rows = conn.execute(
            'SELECT id, role, timestamp FROM conversation_history WHERE conversation_id IS NULL ORDER BY id'
        ).fetchall()
        if not rows:
            return
        chat_id = None
        for message_id, role, timestamp in rows:
            if role == self.MARKER_ROLE:
                chat_id = None
                continue
            if chat_id is None:
                chat_id = self._create_chat(conn, created=timestamp)
            conn.execute('UPDATE conversation_history SET conversation_id = ? WHERE id = ?', (chat_id, message_id))
        if chat_id is None:  # the last thing done was starting a new conversation
            self._create_chat(conn)
        conn.execute('DELETE FROM conversation_history WHERE role = ?', (self.MARKER_ROLE,))

    def _create_chat(self, conn, created=None):
        """Add an empty chat and make it the current one; returns its id."""
        opened = conn.execute('SELECT COALESCE(MAX(opened), 0) + 1 FROM conversations').fetchone()[0]
        cursor = conn.execute(
            'INSERT INTO conversations (created, opened) VALUES (COALESCE(?, CURRENT_TIMESTAMP), ?)',
            (created, opened)
        )
        return cursor.lastrowid

    def _current_chat(self, conn):
        """The current chat's id (a new chat is made if there is none)."""
        row = conn.execute('SELECT id FROM conversations ORDER BY opened DESC, id DESC LIMIT 1').fetchone()
        return row[0] if row else self._create_chat(conn)

    def _chat_exists(self, conn, chat_id):
        return conn.execute('SELECT 1 FROM conversations WHERE id = ?', (chat_id,)).fetchone() is not None

    def add_message(self, role, content):
        """Add a message ('User' or 'Assistant') to the current chat; returns its ID, or None on failure."""
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    'INSERT INTO conversation_history (role, content, conversation_id) VALUES (?, ?, ?)',
                    (role, content, self._current_chat(conn))
                )
                conn.commit()
                return cursor.lastrowid
        except sqlite3.Error as e:
            print(f"Database error adding message: {e}")
            return None

    def current_conversation_id(self):
        """The id of the chat new messages go to."""
        try:
            with self._connect() as conn:
                chat_id = self._current_chat(conn)
                conn.commit()
                return chat_id
        except sqlite3.Error as e:
            print(f"Database error getting the current chat: {e}")
            return None

    def start_new_conversation(self):
        """Start a new chat and return its id (an empty current chat is reused, so they don't pile up)."""
        try:
            with self._connect() as conn:
                chat_id = self._current_chat(conn)
                used = conn.execute(
                    'SELECT 1 FROM conversation_history WHERE conversation_id = ? LIMIT 1', (chat_id,)
                ).fetchone()
                if used:
                    chat_id = self._create_chat(conn)
                conn.commit()
                return chat_id
        except sqlite3.Error as e:
            print(f"Database error starting a new chat: {e}")
            return None

    def list_conversations(self):
        """Chats with messages (id, title, updated, message_count), most recently used first."""
        try:
            with self._connect() as conn:
                rows = conn.execute('''
                    SELECT c.id, c.title, MAX(m.timestamp), COUNT(m.id),
                           (SELECT content FROM conversation_history
                            WHERE conversation_id = c.id AND role = 'User' ORDER BY id LIMIT 1)
                    FROM conversations c JOIN conversation_history m ON m.conversation_id = c.id
                    GROUP BY c.id ORDER BY MAX(m.id) DESC
                ''').fetchall()
            return [{'id': chat_id, 'title': title or automatic_title(first), 'updated': updated,
                     'message_count': count} for chat_id, title, updated, count, first in rows]
        except sqlite3.Error as e:
            print(f"Database error listing chats: {e}")
            return []

    def get_conversation(self, chat_id):
        """A chat's title and messages (oldest first), or None if there is no such chat."""
        try:
            with self._connect() as conn:
                row = conn.execute('SELECT title FROM conversations WHERE id = ?', (chat_id,)).fetchone()
                if row is None:
                    return None
                messages = conn.execute(
                    'SELECT role, content, timestamp FROM conversation_history '
                    'WHERE conversation_id = ? ORDER BY id', (chat_id,)
                ).fetchall()
            first = next((c for r, c, t in messages if r == 'User'), None)
            return {'id': chat_id, 'title': row[0] or automatic_title(first),
                    'messages': [{'role': r, 'content': c, 'timestamp': t} for r, c, t in messages]}
        except sqlite3.Error as e:
            print(f"Database error reading a chat: {e}")
            return None

    def open_conversation(self, chat_id):
        """Make an earlier chat the current one, so it carries on there. False if there is no such chat."""
        try:
            with self._connect() as conn:
                if not self._chat_exists(conn, chat_id):
                    return False
                conn.execute(
                    'UPDATE conversations SET opened = (SELECT MAX(opened) + 1 FROM conversations) WHERE id = ?',
                    (chat_id,)
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"Database error opening a chat: {e}")
            return False

    def rename_conversation(self, chat_id, title):
        """Name a chat (empty: back to the automatic title). False if there is no such chat."""
        title = " ".join((title or "").split())[:100] or None
        try:
            with self._connect() as conn:
                cursor = conn.execute('UPDATE conversations SET title = ? WHERE id = ?', (title, chat_id))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Database error renaming a chat: {e}")
            return False

    def delete_conversation(self, chat_id):
        """Delete a chat (the current one: a new chat starts). Returns the deleted message IDs, None if no such chat."""
        try:
            with self._connect() as conn:
                if not self._chat_exists(conn, chat_id):
                    return None
                was_current = chat_id == self._current_chat(conn)
                message_ids = [row[0] for row in conn.execute(
                    'SELECT id FROM conversation_history WHERE conversation_id = ?', (chat_id,))]
                conn.execute('DELETE FROM conversation_history WHERE conversation_id = ?', (chat_id,))
                conn.execute('DELETE FROM conversations WHERE id = ?', (chat_id,))
                if was_current:
                    self._create_chat(conn)
                conn.commit()
                return message_ids
        except sqlite3.Error as e:
            print(f"Database error deleting a chat: {e}")
            return None

    def get_all_messages(self, limit=None):
        """Messages (role, content, timestamp) of all chats, oldest first; `limit`: only the most recent ones."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    'SELECT role, content, timestamp FROM conversation_history '
                    'WHERE role != ? ORDER BY id DESC LIMIT ?',
                    (self.MARKER_ROLE, limit if limit and limit > 0 else -1)
                ).fetchall()
            return [{'role': r, 'content': c, 'timestamp': t} for r, c, t in reversed(rows)]
        except sqlite3.Error as e:
            print(f"Database error getting messages: {e}")
            return []

    def get_last_n_messages(self, n=5):
        """The last `n` messages of the current chat, oldest first."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    'SELECT role, content FROM conversation_history WHERE conversation_id = ? '
                    'ORDER BY id DESC LIMIT ?',
                    (self._current_chat(conn), n)
                ).fetchall()
                conn.commit()
            return [{'role': r, 'content': c} for r, c in reversed(rows)]
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return []

    def format_for_prompt(self, messages, max_chars=500):
        """Format messages for the prompt, keeping at most `max_chars` of each."""
        return "".join(f"{m['role']}: {m['content'][:max_chars]}\n" for m in messages)

    def count_messages(self):
        """Count all messages in all chats."""
        try:
            with self._connect() as conn:
                return conn.execute(
                    'SELECT COUNT(*) FROM conversation_history WHERE role != ?', (self.MARKER_ROLE,)
                ).fetchone()[0]
        except sqlite3.Error as e:
            print(f"Database error counting messages: {e}")
            return 0
