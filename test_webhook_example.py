"""Deterministic integration tests using real, temporary SQLite databases."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from webhook_example import PayloadConflict, handle_event


SCHEMA = """
CREATE TABLE receipts (
    event_id TEXT PRIMARY KEY NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE tickets (
    ticket_id TEXT PRIMARY KEY NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0
);
INSERT INTO tickets (ticket_id) VALUES ('T-1'), ('T-2');
"""


class CommitProbe(sqlite3.Connection):
    """Test-only seam: run a hook immediately before the real SQL COMMIT."""

    before_commit = None

    def execute(self, sql, parameters=(), /):
        if sql == "COMMIT" and self.before_commit is not None:
            self.before_commit()
        return super().execute(sql, parameters)


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tickets.sqlite"
        with closing(self.connect()) as db:
            db.executescript(SCHEMA)
        self.payload = {"ticket_id": "T-1", "kind": "note.added"}

    def connect(self, **kwargs):
        return sqlite3.connect(self.path, autocommit=True, **kwargs)

    def state(self):
        with closing(self.connect()) as db:
            tickets = dict(db.execute("SELECT ticket_id, event_count FROM tickets"))
            receipts = db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
            return tickets, receipts

    def test_repeat_delivery_counts_once(self):
        with closing(self.connect()) as db:
            self.assertEqual(handle_event(db, "evt-1", self.payload), "applied")
            reordered = {"kind": "note.added", "ticket_id": "T-1"}
            self.assertEqual(handle_event(db, "evt-1", reordered), "duplicate")
        self.assertEqual(self.state(), ({"T-1": 1, "T-2": 0}, 1))

    def test_failure_before_commit_rolls_back_then_retry_applies(self):
        def fail():
            raise RuntimeError("injected before commit")

        with closing(self.connect(factory=CommitProbe)) as db:
            db.before_commit = fail
            with self.assertRaisesRegex(RuntimeError, "injected before commit"):
                handle_event(db, "evt-1", self.payload)
            self.assertFalse(db.in_transaction)
        self.assertEqual(self.state(), ({"T-1": 0, "T-2": 0}, 0))
        with closing(self.connect()) as db:
            self.assertEqual(handle_event(db, "evt-1", self.payload), "applied")
        self.assertEqual(self.state(), ({"T-1": 1, "T-2": 0}, 1))

    def test_reused_id_with_changed_payload_is_rejected(self):
        with closing(self.connect()) as db:
            self.assertEqual(handle_event(db, "evt-1", self.payload), "applied")
            changed = {"ticket_id": "T-2", "kind": "note.added"}
            with self.assertRaises(PayloadConflict):
                handle_event(db, "evt-1", changed)
            self.assertFalse(db.in_transaction)
        self.assertEqual(self.state(), ({"T-1": 1, "T-2": 0}, 1))

    def test_distinct_ids_each_count(self):
        with closing(self.connect()) as db:
            self.assertEqual(handle_event(db, "evt-1", self.payload), "applied")
            self.assertEqual(handle_event(db, "evt-2", self.payload), "applied")
        self.assertEqual(self.state(), ({"T-1": 2, "T-2": 0}, 2))

    def test_unknown_ticket_does_not_leave_a_receipt(self):
        with closing(self.connect()) as db:
            with self.assertRaisesRegex(ValueError, "unknown ticket"):
                handle_event(db, "evt-1", {"ticket_id": "missing"})
            self.assertFalse(db.in_transaction)
        self.assertEqual(self.state(), ({"T-1": 0, "T-2": 0}, 0))

    def test_existing_transaction_is_not_rolled_back(self):
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            with self.assertRaisesRegex(ValueError, "idle connection"):
                handle_event(db, "evt-1", self.payload)
            self.assertTrue(db.in_transaction)
            db.execute("ROLLBACK")

    def test_incompatible_connection_mode_is_rejected(self):
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaisesRegex(ValueError, "autocommit=True"):
                handle_event(db, "evt-1", self.payload)

    def test_concurrent_same_event_busy_then_retry_is_duplicate(self):
        writer_ready = threading.Event()
        release_writer = threading.Event()

        def hold_before_commit():
            writer_ready.set()
            if not release_writer.wait(timeout=5):
                raise TimeoutError("test failed to release writer")

        def first_delivery():
            # This connection belongs to the worker that creates it.
            with closing(self.connect(factory=CommitProbe)) as db:
                db.before_commit = hold_before_commit
                return handle_event(db, "evt-1", self.payload)

        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(first_delivery)
            try:
                self.assertTrue(writer_ready.wait(timeout=5), "writer never reached COMMIT")
                with closing(self.connect(timeout=0)) as second:
                    with self.assertRaises(sqlite3.OperationalError) as caught:
                        handle_event(second, "evt-1", self.payload)
                    self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
                    self.assertFalse(second.in_transaction)
            finally:
                release_writer.set()
            self.assertEqual(first.result(timeout=5), "applied")

        with closing(self.connect()) as retry:
            self.assertEqual(handle_event(retry, "evt-1", self.payload), "duplicate")
        self.assertEqual(self.state(), ({"T-1": 1, "T-2": 0}, 1))


if __name__ == "__main__":
    unittest.main()
