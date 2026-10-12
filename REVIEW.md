# Review of the first kit and v2 changes

| Finding in the first kit | Effect | v2 change |
|---|---|---|
| SQLite write transactions also handled rate-limit bookkeeping | Enquiries and abuse controls contended for the same writer | PostgreSQL for records; atomic Redis rolling windows for rate limits |
| No idempotency token | Timeout/retry could create duplicate enquiries | UUID request key, unique database constraint, keyed payload fingerprint and conflict response |
| Fixed rate windows | Window-boundary bursts | Rolling Redis sets checked and updated in one Lua operation |
| Limited resource boundaries | Slow/chunked requests or dependency delays could consume capacity | Actual streamed-body byte cap, read/request deadlines, pool/statement/lock/concurrency bounds |
| No mail delivery path | Staff had to inspect records manually | Transactional outbox and optional separate TLS SMTP worker with leases/retries |
| Page/image files served by the Python process | Normal visits consumed API-serving resources | Caddy serves static traffic directly and independently |
| Full-size imagery and mutable text assets | Extra mobile downloads and CPU compression work | Responsive/lazy images, fingerprinted assets and precompressed text |
| Simple production runtime identity | Future DB administrator credentials could reach the API | Separate bootstrap credentials and DML-only application role |
| No documented dependency/failure load evidence | Capacity was an assumption | 36 regression cases, real Redis tests, 100-client HTTP workload and explicit validation limits |

Origin checks protect browser submissions, not all automated clients. Rate limiting and resource caps do not guarantee DDoS immunity. SMTP is at least once and may duplicate after a crash. Runtime logs contain request identifiers, route categories, durations and status, not enquiry text or credential values. Static reads continue through Caddy when API/database dependencies fail; new enquiries return a safe error until dependencies recover.

The rebuild exceeds the requested code minimum through useful modules rather than adding duplicate implementations. PostgreSQL/Docker/SMTP and browser launch checks remain required; see VERIFICATION.md. Line count is not the evidence of strength.
