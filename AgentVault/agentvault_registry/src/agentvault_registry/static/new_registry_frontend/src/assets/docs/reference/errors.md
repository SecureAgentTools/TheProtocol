# Error Types

Every error a registry or a TEG sends carries a `type`: a URL of the form `https://docs.theprotocol.cloud/errors/<type>`. This page is what that URL names. Each section below is one `type`, in the order of its HTTP status, with what it means and what to do. The body's shape (the legacy `error` object beside the RFC 7807 fields) is in [the API chapter](/docs/09#error-shapes), and the route-level `error.code` values are in its table.

A `type` is stable: branch on the HTTP status and the `type`, and show the `detail` sentence to people. A refusal a route raised itself carries no `error.code`; a database refusal does.

## bad_request

HTTP 400. The request was refused as given: a field the route could not use, a value outside what it allows, a state it cannot act on (an amount above a balance, an unknown event type). `detail` names which. Change the request; sending it again unchanged is refused again.

## unauthorized

HTTP 401. The credential is missing, expired, revoked or of the wrong kind: a developer token where an agent token is wanted, or the other way round. A `WWW-Authenticate` header is on the response. Sign in again, or get the right kind of credential (the quickstart shows both).

## forbidden

HTTP 403. The caller is authenticated and not allowed: a missing admin flag, a permission the agent's roles do not hold (`detail` names it), a feature the registry has switched off, a suspended agent. A different credential or an owner's change of roles is the way forward, not a retry.

## not_found

HTTP 404. There is no such object or route on this registry. Two refusals say which registry is wrong: a frame-only route asked of a registry that is not a frame (`detail` starts with `mainframe_only:`), and a cloud operator's own route asked of a frame (`operator_only:`). Check the identifier, and that you asked the registry that holds it.

## conflict

HTTP 409. The request conflicts with existing state: a name already taken, an object already in the state asked for, a write the database refused (`error.code` is then `DUPLICATE_ENTRY`, `FOREIGN_KEY_VIOLATION`, `NULL_CONSTRAINT_VIOLATION` or `INTEGRITY_ERROR`). Read the current state and decide; a retry of the same request fails the same way.

## validation_error

HTTP 422. The request does not validate: the body or a parameter has the wrong shape (`error.code` `VALIDATION_FAILED`, `error.field` names the path), a value is out of range (`PARAM_OUT_OF_RANGE`) or text holds a NUL (`NUL_IN_TEXT`). Fix the field named and send it again.

## too_early

HTTP 425. "Not yet": the answer would be given sooner than a rule allows (for example a liability mandate's presence step asked before its read floor has passed). The request is not wrong; wait and ask again.

## rate_limit_exceeded

HTTP 429. A route's own limit was reached. `Retry-After` says when to ask again. The global limiter answers differently, as the API chapter says under rate limits.

## internal_server_error

HTTP 500. A fault on the registry's side that the registry did not expect. Nothing in the request is known to be wrong. `error.code` is `INTERNAL_ERROR`. Try again; if it persists, the operator of the registry can find it in the log by the time and the `instance` path.

## database_error

HTTP 500, with `error.code` `DATABASE_ERROR`. The database refused or failed a statement the route sent. Like `internal_server_error` it is the registry's side; it is named separately because it is the fault an operator looks for in the database's log.

## service_unavailable

HTTP 503. The registry could not take the call just now: the database is busy (`error.code` `DATABASE_BUSY`), a service it depends on (the TEG, the event store) did not answer, or it is starting. Try again later and read `Retry-After`.

## error

Any other status. The registry has no more specific `type` for it; `title` and `status` say what happened. Treat it by its HTTP status.
