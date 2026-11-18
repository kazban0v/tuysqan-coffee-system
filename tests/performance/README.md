# Local PostgreSQL + Gunicorn performance fixture

All fixtures live in a new PostgreSQL cluster under `artifacts/postgres-performance/run/data`.
`config.perf_settings` refuses to start without the explicit local benchmark flag and
refuses a database name outside `tuysqan_perf_*`. It never falls back to SQLite.
Secrets, sessions and QR tokens are in the private `run/` directory (0700, files 0600).
Do not publish or package that directory.

Install the separate benchmark dependencies into the existing project virtualenv:

```sh
.venv/bin/python -m pip install -r requirements-performance.txt
```

A local PostgreSQL installation providing `initdb`, `pg_ctl`, `postgres` is required.
The harness starts its own cluster on randomly selected loopback ports, with fsync
and synchronous_commit enabled, 128 MB shared buffers, 32 max connections and 4 MB
work_mem. Existing PostgreSQL services and business databases are not touched.

```sh
.venv/bin/python scripts/perf_postgres.py --duration 40
```

This seeds the private fixture once (36,500 historical orders, 2,000 historical
customers, 100 independent phone-first guest sessions), starts Gunicorn with two
workers and two threads each, runs 10/30/50/100 clients and write/idempotency tests,
checks the persisted records, then stops Gunicorn and its PostgreSQL cluster.
A later run reuses the dedicated fixture and checks only that run's expected keys.
The integrity report includes before/after deltas so prior synthetic orders are not
mistaken for unexplained writes. `--init-only` leaves the dedicated cluster up;
`--stop` stops only this fixture.

```sh
.venv/bin/python scripts/perf_postgres.py --clients 100 --duration 60 \
  --output artifacts/postgres-performance/postgres-gunicorn-recheck.json
```

For the backend regression suite against PostgreSQL (a separate Django test DB):

```sh
.venv/bin/python scripts/perf_postgres.py --init-only
TUYSQAN_PERF_LOCAL=1 \
TUYSQAN_PERF_SECRETS="$PWD/artifacts/postgres-performance/run/secrets.json" \
DJANGO_SETTINGS_MODULE=config.perf_settings \
.venv/bin/python manage.py test --noinput --settings=config.perf_settings
.venv/bin/python scripts/perf_postgres.py --stop
```

## Measurement limits

The executed environment is native macOS ARM64 with 16 GB host RAM, not a Linux VPS.
No Docker, Podman, Lima, QEMU or equivalent runtime was available. Two Gunicorn workers
are **not** a hard limit of two vCPUs, and neither a 2 GB nor 4 GB aggregate memory
limit was enforced. RSS is sampled once per second across Gunicorn master/workers and
all PostgreSQL processes. Its sum can count shared pages several times. USS could not
be obtained for the child processes and is reported as unavailable, not zero.
CPU 100% means one fully occupied logical CPU; the observed short peak exceeds 200%.
The local load generator is excluded from the application/DB memory and CPU totals.

Clients use real HTTP, sessions, CSRF, orders, PostgreSQL row locks and durable commits.
They poll guest statuses every 3 seconds (production: 12) and staff queues every
2 seconds (production: 10). Each stage includes an initial burst of orders and a full
cashier/payment/kitchen/bar/ready/served lifecycle. This is deliberately more aggressive
than ordinary polling. It is a closed-loop workload; RPS is measured, not a configured
request rate or a claim about saturation throughput. Single-stage 40–60 second runs
are not an all-day soak test or a proof of one-year availability.

HTTP is loopback without TLS, Nginx, a browser or image downloads. The fixture tests
backend load, not mobile network speed or complete infrastructure memory consumption.
Do not report these timings as measured performance of a 2 GB/2 vCPU RackNerd machine.
