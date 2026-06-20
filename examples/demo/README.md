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

## What the demo proves

Across the whole codebase LogicChart builds deterministic workflow models without adding a
review queue. Enum and state-machine decisions are still captured as domain metadata on
nodes and flows, so agents can explain what each workflow does without treating inferred
gaps as defects.

## Explore it

```bash
logicchart update examples/demo --full       # refresh the deterministic model
logicchart validate examples/demo --check-sync
logicchart view examples/demo                # interactive manual viewer
```

For codebase questions, configure an agent with `logicchart setup-agent <target>` in the
project you want to inspect, then ask ordinary questions such as "where is suspended user
status handled?" or "show the order fulfillment workflow." Those capabilities live behind
MCP workflow slices rather than public demo CLI commands.

The generated model lives in [`logicchart-out/`](logicchart-out/): `logic-flow.json`
(the IR), `logic-flow.md` (Markdown + Mermaid), and `logic-flow.html` (the viewer).
