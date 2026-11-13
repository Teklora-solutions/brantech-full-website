# MCP connection fallback repair

## Diagnosis
The installed and repository MCP scripts are identical. A fresh stdio tools/call hangs beyond 40 seconds. Socket tracing shows urllib attempting an IPv6 connection with a 30-second timeout; both advertised IPv6 addresses can consume Pi's entire 60-second tool deadline before IPv4 is tried. Direct IPv4 connects in 0.13 seconds and an authenticated read-only task API request succeeds.

## Execution
- [x] Reproduce independently of Pi and confirm working authenticated IPv4 connectivity.
- [x] Add a client-local connection factory with a 3-second per-address limit and 10-second shared TCP-connect budget; preserve a 30-second HTTP I/O timeout and standard TLS validation.
- [x] Test fallback, socket cleanup, budget exhaustion, handler wiring and stdio error responses without external dependencies.
- [x] Run affected tests, update setup documentation and install the repaired script locally.
- [x] Verify read-only task requests through the repaired stdio server. No live task mutations or production deployment.

## Verification
- Six focused transport regression tests pass using `manage.py test staff.tests.test_mcp_transport`.
- Combined staff/tasks suite: 327 tests pass. The first run exceeded the 200-second command limit; the completed run used Django's MD5 password hasher only in the test process to avoid slow password hashing. No application settings changed.
- Installed `~/.teklora/teklora_mcp.py` updated with owner-only executable permissions; fresh configured stdio task call succeeds in 7.09 seconds.
- Authenticated read-only team-board query returns nine active tasks (eight open, one in review). No API data or credentials added to the repository.
- Existing running MCP processes require reconnect/reload to load the repaired script.
