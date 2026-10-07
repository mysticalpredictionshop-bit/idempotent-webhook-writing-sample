"""Python 3.12+ educational transaction example, not an HTTP server.

The caller owns the connection and validates/authenticates incoming events.
The payload must be a JSON-compatible dictionary with string keys and a
ticket_id referring to an existing ticket. Each event increments its counter.
See test_webhook_example.py for the small schema and runnable examples.
"""

import json


class PayloadConflict(ValueError):
    """An event ID was reused for a different payload."""


def handle_event(db, event_id, payload):
    """Return 'applied' or 'duplicate'; propagate conflicts and DB failures.

    Use an idle sqlite3 connection created with autocommit=True. Never share
    one connection between concurrent callers. Deduplication lasts only as
    long as its receipt is retained in this same database.
    """
    if db.autocommit is not True or db.in_transaction:
        raise ValueError("use an idle connection with autocommit=True")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    try:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT payload FROM receipts WHERE event_id = ?", (event_id,)
        ).fetchone()
        if prior is not None:
            if prior[0] != body:
                raise PayloadConflict("event ID reused with a different payload")
            outcome = "duplicate"
        else:
            db.execute(
                "INSERT INTO receipts (event_id, payload) VALUES (?, ?)",
                (event_id, body),
            )
            changed = db.execute(
                "UPDATE tickets SET event_count = event_count + 1 WHERE ticket_id = ?",
                (payload["ticket_id"],),
            )
            if changed.rowcount != 1:
                raise ValueError("unknown ticket")
            outcome = "applied"
        db.execute("COMMIT")
        return outcome
    except BaseException:
        # Also clean up for an interrupt; never silently acknowledge a failure.
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
