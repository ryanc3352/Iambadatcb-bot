import sqlite3
from contextlib import closing
from pathlib import Path


class ConversationHistory:
    """Manages conversation history storage using SQLite database.

    Stores user and assistant messages with timestamps for persistent
    conversation tracking and context retrieval.
    """

    def __init__(self, db_path="conversation_history.db"):
        """Initialize conversation history database.

        Args:
            db_path (str): Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_table()

    def _connect(self):
        """Open a connection that is closed when the `with` block ends."""
        return closing(sqlite3.connect(str(self.db_path)))

    def create_table(self):
        """Create conversation_history table if it doesn't exist."""
        with self._connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    def add_message(self, role, content):
        """Add a message to conversation history.

        Args:
            role (str): 'User' or 'Assistant'
            content (str): Message content

        Returns:
            int | None: ID of the new message, or None on failure
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    'INSERT INTO conversation_history (role, content) VALUES (?, ?)',
                    (role, content)
                )
                conn.commit()
                return cursor.lastrowid
        except sqlite3.Error as e:
            print(f"Database error adding message: {e}")
            return None

    def get_all_messages(self):
        """Get all messages from conversation history.

        Returns:
            list: List of message dictionaries with role, content and timestamp
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    'SELECT role, content, timestamp FROM conversation_history ORDER BY id'
                ).fetchall()
            return [{'role': r, 'content': c, 'timestamp': t} for r, c, t in rows]
        except sqlite3.Error as e:
            print(f"Database error getting messages: {e}")
            return []

    def get_last_n_messages(self, n=5):
        """Get the last N messages from conversation history.

        Args:
            n (int): Number of recent messages to retrieve

        Returns:
            list: The most recent N messages, oldest first
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    'SELECT role, content FROM conversation_history ORDER BY id DESC LIMIT ?',
                    (n,)
                ).fetchall()
            return [{'role': r, 'content': c} for r, c in reversed(rows)]
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return []

    def format_for_prompt(self, messages, max_chars=500):
        """Format message list for inclusion in LLM prompt.

        Args:
            messages (list): List of message dictionaries
            max_chars (int): Maximum characters kept from each message

        Returns:
            str: Formatted conversation history string
        """
        return "".join(f"{m['role']}: {m['content'][:max_chars]}\n" for m in messages)

    def count_messages(self):
        """Count total messages in database.

        Returns:
            int: Total number of messages
        """
        try:
            with self._connect() as conn:
                return conn.execute('SELECT COUNT(*) FROM conversation_history').fetchone()[0]
        except sqlite3.Error as e:
            print(f"Database error counting messages: {e}")
            return 0

    def clear_history(self):
        """Clear all conversation history.

        Returns:
            bool: True if successful
        """
        try:
            with self._connect() as conn:
                conn.execute('DELETE FROM conversation_history')
                conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Database error clearing history: {e}")
            return False
