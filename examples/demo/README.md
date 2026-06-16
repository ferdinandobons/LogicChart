# LogicChart demo: a polyglot, multi-scope codebase

A small but realistic "users & orders" platform, deliberately spread across **11
languages** and **3 macro-parts** to show LogicChart representing a whole codebase,
a single scope, or one flow, all from the same deterministic model.

## Layout

| Scope      | Path             | Language    | What it does                          |
| ---------- | ---------------- | ----------- | ------------------------------------- |
| `backend`  | `backend/users.py`             | Python      | FastAPI user endpoint                 |
| `backend`  | `backend/orders/service.go`    | Go          | Order lifecycle state machine         |
| `backend`  | `backend/billing/BillingService.java` | Java | Payment settlement                    |
| `backend`  | `backend/auth/AuthService.cs`  | C#          | Role-based access checks              |
| `backend`  | `backend/catalog/Catalog.php`  | PHP         | Catalog reorder logic                 |
| `backend`  | `backend/notifications/notifier.rb` | Ruby   | Channel-based delivery                |
| `frontend` | `frontend/app/api/users/route.ts`   | TypeScript | User API route                  |
| `frontend` | `frontend/app/api/orders/route.ts`  | TypeScript | Order API route                 |
| `frontend` | `frontend/app/users/page.tsx`  | TypeScript  | User dashboard page                   |
| `frontend` | `frontend/lib/status.js`       | JavaScript  | Status label helper                   |
| `edge`     | `edge/cache.c`                 | C           | Cache eviction policy                 |
| `edge`     | `edge/native/*.cpp`            | C++         | Native admission and cache policies   |
| `edge`     | `edge/router/src/lib.rs`       | Rust        | Request router (exhaustive `match`)   |

## The one finding

Across the whole codebase LogicChart surfaces exactly **one** finding:
`frontend/app/api/users/route.ts` switches on `user.status` and handles
`UserStatus.ACTIVE` and `UserStatus.SUSPENDED`, but the `UserStatus` enum also
declares `DELETED`, which is unhandled with no `default`. Because the enum is a
declared closed set, LogicChart names the missing member precisely
(`enum_exhaustiveness`, evidence `INFERRED`). The JavaScript helper in
`frontend/lib/status.js` switches on the same statuses and *does* handle
`deleted`, so it is clean: the contrast is the point. Every other service
(including the Rust `match`, which the compiler already proves exhaustive) is
reported clean: the model stays precise as the codebase grows.

## Explore it

```bash
logicchart analyze examples/demo --full      # whole codebase
logicchart view examples/demo                # interactive viewer (scope + language filters)
logicchart query "where is suspended user status handled?" --path examples/demo
logicchart query "order status" --path examples/demo --scope backend
logicchart impact backend/users.py --path examples/demo
```

The generated model lives in [`logicchart-out/`](logicchart-out/): `logic-flow.json`
(the IR), `logic-flow.md` (Markdown + Mermaid), and `logic-flow.html` (the viewer).
