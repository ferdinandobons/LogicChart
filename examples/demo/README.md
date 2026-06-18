# LogicChart demo: a dense frontend/backend codebase

A small but realistic "users & orders" platform, deliberately spread across **11
languages** and **2 macro-parts** to show LogicChart representing a broad
frontend/backend system, a single scope, or one flow, all from the same deterministic
model.

## Layout

| Scope      | Path                               | Language    | What it does                          |
| ---------- | ---------------------------------- | ----------- | ------------------------------------- |
| `backend`  | `backend/users.py`                 | Python      | FastAPI user read/update workflow     |
| `backend`  | `backend/orders/service.go`        | Go          | Order fulfillment state machine       |
| `backend`  | `backend/billing/BillingService.java` | Java     | Payment and refund settlement         |
| `backend`  | `backend/auth/AuthService.cs`      | C#          | Role/resource access policy           |
| `backend`  | `backend/catalog/Catalog.php`      | PHP         | Catalog reorder and merchandising     |
| `backend`  | `backend/notifications/notifier.rb` | Ruby       | Multi-channel notification routing    |
| `backend`  | `backend/cache/cache.c`            | C           | Backend cache eviction policy         |
| `backend`  | `backend/native/*.cpp`             | C++         | Native admission and cache policies   |
| `backend`  | `backend/router/src/lib.rs`        | Rust        | Backend request router                |
| `frontend` | `frontend/app/api/users/route.ts`  | TypeScript  | User API route and moderation flow    |
| `frontend` | `frontend/app/api/orders/route.ts` | TypeScript  | Order API route and action planner    |
| `frontend` | `frontend/app/users/page.tsx`      | TypeScript  | User dashboard page                   |
| `frontend` | `frontend/lib/status.js`           | JavaScript  | Status labels and visual tones        |

## Intentional findings

Across the whole codebase LogicChart surfaces exactly **two** findings, both in the
frontend API layer:

- `frontend/app/api/orders/route.ts` switches on `order.state` and omits
  `OrderState.RETURNED`, `OrderState.CHARGEBACK`, and `OrderState.BACKORDERED`.
- `frontend/app/api/users/route.ts` switches on `user.status` and omits
  `UserStatus.DELETED`, `UserStatus.ARCHIVED`, and `UserStatus.LOCKED`.

Both findings are `enum_exhaustiveness` with `INFERRED` evidence. The JavaScript helper in
`frontend/lib/status.js` handles every user status, so it stays clean: the contrast is the
point. Every backend service (including the Rust `match`, which the compiler already proves
exhaustive) is reported clean, so the demo stays precise while still giving the review panel
multiple realistic problems to show.

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
