# Observability Module

Owns structured logging, runtime snapshots, runtime invalidation events, and
operator-facing summaries.

Runtime refresh notes:

- Runtime snapshots remain the canonical observability payload consumed by the
  dashboard and issue-detail REST endpoints.
- Runtime invalidation events are lightweight hints that tell browsers to
  re-fetch those REST snapshots. They do not carry full runtime state.
- The SSE invalidation stream is intentionally scoped to low-concurrency
  internal usage on the current WSGI sidecar. Each open stream holds a worker
  thread for the lifetime of the connection.
- The invalidation broker is process-local in memory, so streamed invalidations
  are only visible to clients connected to the same sidecar process.
