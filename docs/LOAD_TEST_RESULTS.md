# PostgreSQL workload observation

Executed locally on Windows with Python 3.13 and portable PostgreSQL 17.11, using `python -m scripts.load_test --requests 100 --workers 8`. Docker Desktop was unavailable because its backend crashed, so the run used EDB's portable binaries in the ignored local folder. No system PostgreSQL installation or existing application database was changed by the load test.

| Scenario | Attempts / workers | Result | Attempts/sec | p50 / p95 latency |
| --- | --- | --- | --- | --- |
| Ordinary checkout | 100 / 8 | 100 successful orders | 147.59 | 49.89 / 62.48 ms |
| Last item contention | 16 / 8 | 1 order, 15 stock conflicts | 75.16 | 45.56 / 148.93 ms |
| Duplicate checkout | 16 / 8 | 16 responses resolving to 1 order | 81.01 | 44.11 / 134.96 ms |

All seven correctness checks passed: expected success count, one last-item winner, a single receipt for retries, exact remaining stock, exact order count, matching order/item totals, and preserved carts for rejected buyers.

These are one-run observations, not a performance guarantee. The test runs Flask's WSGI request lifecycle against real PostgreSQL, excluding network, proxy/TLS, catalogue/cart setup and console logging. It includes per-request database connection setup. The ordinary scenario deliberately contends on one shared product row. The 100-order sample is a smoke/load exercise, not sustained production capacity testing. Repeat under your intended server, workload and hardware before drawing capacity conclusions.

The sanitized machine-readable result is [load-results.json](load-results.json). Reproduce the workload and interpret its scope using [OPERATIONS.md](OPERATIONS.md).
