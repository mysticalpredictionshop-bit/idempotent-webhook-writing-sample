# Retries are not exactly-once: testing a small idempotent webhook handler

A webhook sender can lose the response after your database commits. Retrying is reasonable: the sender cannot tell whether the receiver finished. But if every delivery increments a counter, one event now counts twice. The useful question is narrower than “did this request run once?”: can repeated deliveries change the stored result more than once?

This example counts events for two fictional support tickets. It uses Python's standard library and a local SQLite file. The receipt that identifies a processed event and the counter update commit together. The accompanying tests exercise failures and contention, rather than relying on two successful calls alone.

## Define the boundary first

For an event ID and matching payload, the intended result is one committed counter increment. A repeat returns “duplicate”. Reusing the ID with different content raises PayloadConflict. This contract assumes stable event IDs, a retained receipt, and every delivery reaching the same database.

The receipts table has a non-null primary key on event_id and stores the serialized payload. The tickets table contains ticket_id and event_count. Keeping both in one transaction matters: committing a receipt first could suppress a retry of work that never completed; committing the increment first could let a retry increment again.

In webhook_example.py, handle_event accepts an idle connection, an event ID, and a parsed payload containing ticket_id. The caller must authenticate and validate incoming events before calling it. JSON keys are sorted for comparison, so reversing dictionary key order does not create a conflict. This is a deliberately small comparison rule, not a general definition of equivalent JSON documents.

## Make the transaction visible

The handler starts with BEGIN IMMEDIATE, checks for an existing receipt, and compares its payload. For a new event, it inserts the receipt and increments the selected ticket's counter. An unknown ticket raises an error. Only then does it execute COMMIT and return “applied”. An exception rolls back an active transaction and propagates to the caller.

SQLite allows only one write transaction at a time. BEGIN IMMEDIATE acquires that position before the receipt lookup, so two writers cannot both inspect the same absent receipt inside their write transactions. A competing writer may instead receive SQLITE_BUSY. The primary key adds a database constraint against duplicate receipt IDs. [1]

The connection uses autocommit=True explicitly, requiring Python 3.12 or later. Here, transactions are controlled with SQL statements. Python's connection.commit() and connection.rollback() methods have no effect in this mode, so substituting those methods would break this example. Connections must be closed explicitly; each concurrent caller creates its own. [2]

## Test the awkward paths

Run the complete example from the extracted folder:

    python3 -B -W error -m unittest -v

No package installation, server, account, or network call is needed. The tests create temporary database files and inspect persisted state through fresh connections.

Four tests establish the central behavior:

1. Repeat delivery. Submit evt-1 twice, with the same fields in different orders. The results are “applied” and “duplicate”; the database contains one receipt and one increment.

2. Concurrent delivery. Pause the first writer immediately before COMMIT. While that transaction remains open, deliver the same event on another connection with timeout=0. Assert SQLITE_BUSY, release the first writer, and retry. The retry is a duplicate, and the count remains one. threading.Event coordinates these steps; five-second waits are deadlock guards, not timing-based success criteria. [3]

3. Failure before commit. A test-only connection subclass raises at the COMMIT boundary, after both writes. Assert that neither write survived, then retry through a normal connection and verify one increment. This tests exception rollback, not a power failure or killed process.

4. Conflicting payload. Process evt-1 for T-1, then reuse it for T-2. Assert PayloadConflict and verify that T-2 remains unchanged.

Four additional tests cover distinct event IDs, unknown tickets, incompatible transaction modes, and preserving a caller's existing transaction. On the recorded run, all eight passed using Python 3.12.14 and SQLite 3.53.1. That is evidence for this local example, not a claim about throughput or production reliability.

## Know what remains outside

Do not put an email send or external API request between BEGIN and COMMIT and assume it becomes atomic. SQLite cannot roll back another service's action. A transactional outbox can record an intention beside the counter, but its delivery still needs its own retry and deduplication design.

Even locally, deleting receipts removes the memory of processed events. Reusing IDs across tenants or providers would also need a properly scoped key. Contention needs an explicit retry policy; this handler exposes errors rather than retrying indefinitely or acknowledging failed work.

This is an educational transaction example, not a complete production webhook server or security audit. It omits HTTP handling, signatures, replay-window enforcement, payload limits, monitoring, and crash testing. Its useful promise is specific: within this database and retained receipt history, a successful matching retry does not increment the ticket again.

## Sources checked October 7, 2026

[1] SQLite transaction control
https://www.sqlite.org/lang_transaction.html

[2] Python sqlite3 connection and transaction documentation
https://docs.python.org/3.12/library/sqlite3.html

[3] Python threading Event objects
https://docs.python.org/3.12/library/threading.html#event-objects

Further detail: SQLite isolation and SQLITE_BUSY
https://www.sqlite.org/isolation.html
https://www.sqlite.org/rescode.html#busy
