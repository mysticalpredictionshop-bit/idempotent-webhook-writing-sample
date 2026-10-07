# Retries are not exactly-once

An independent technical-writing sample explaining a small idempotent webhook
handler with Python and SQLite, supported by runnable tests.

**[Read the article: Retries are not exactly-once](article.md)**

## Contents

- [Article](article.md): the explanation, boundaries, and official source links
- [Handler](webhook_example.py): the small database transaction example
- [Tests](test_webhook_example.py): runnable tests and the database schema
- [Verification record](verification.txt): execution results and verification limits

## Run the tests

1. Download or clone this repository.
2. Use Python 3.12 or later with its sqlite3 module available.
3. From the repository folder, run:

```sh
python3 -B -W error -m unittest -v
```

All eight tests passed on Python 3.12.14 with SQLite 3.53.1. Only Python
standard-library modules are used. No package installation, external service,
credentials, network requests, or persistent database setup is needed.
The tests create fictional tickets T-1 and T-2 in temporary local databases.

## Scope and limitations

This is an educational transaction example, not a deployable webhook service.
The handler assumes the caller has authenticated and validated incoming events.
It omits HTTP handling, signatures, replay-window enforcement, payload limits,
monitoring, and crash testing. Read the article's limitations before adapting it.

## Provenance

This independent educational demonstration was prepared with AI on October 7,
2026. It uses synthetic data and contains no client or personal data.
It is not commissioned client work, a paid client case, or a human-reviewed
article. The public repository is a limited writing sample, not a delivery of
client-specific work.
