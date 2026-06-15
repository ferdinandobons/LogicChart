# examples/shop — expected findings

A worked corpus: a small shop backend (Python) + frontend (Next.js/TS) with
**planted defects** and **controls**, used to validate LogicChart end-to-end and
to be candid about what the current detectors catch and miss. The gated
detectors are enabled here (`gated_detectors = true`). Regenerate with
`logicchart analyze examples/shop`.

## True positives

| Detector | Flow | Where | Planted |
|---|---|---|---|
| `dead_code` | `load_profile` | `backend/users_service.py` | #9 code after `return` |
| `missing_branch` | `POST` | `frontend/app/api/orders/route.ts` | `switch` with no default |
| `missing_branch` | `OrdersPage` | `frontend/app/orders/page.tsx` | if/else-if with no else |
| `enum_exhaustiveness` | `transition` | `backend/orders_service.py` | #4 omits CANCELLED/DELIVERED/REFUNDED |
| `enum_exhaustiveness` | `handle_result` | `backend/payments_service.py` | #5 omits PaymentResult.FRAUD_REVIEW |
| `enum_exhaustiveness` | `change_email` | `backend/api/users_routes.py` | #3 omits AccountStatus ACTIVE/PENDING_VERIFICATION |
| `no_op_branch` | `summarize` | `backend/orders_service.py` | #10 empty refunded branch |
| `broad_except_swallow` | `charge` | `backend/payments_service.py` | #6 `except: pass` |
| `dead_guard` | `charge` | `backend/payments_service.py` | #11 `ENABLE_DOUBLE_CHARGE_GUARD` is always `False` |
| `broad_except_swallow` | `processCheckout` | `frontend/app/api/checkout/route.ts` | empty `catch` |
| `logging_asymmetry` | `capture_payment` | `backend/payments_service.py` | #14 silent where `refund_payment` logs+raises |
| `auth_divergence` (gated) | `purge_user` | `backend/api/admin_routes.py` | #12 missing the `require_role` its sibling `delete_user` performs |

A state-like dispatch with no fallback would fire both `missing_branch` and
`enum_exhaustiveness`; the generic `missing_branch` is now suppressed on a node
the declared-set check already covers, so `change_email`/`handle_result`/`transition`
carry only the more actionable `enum_exhaustiveness`.

## Gated-detector false positive (candidly shown)

- `auth_divergence` also flags `load_profile` (`users_service.py`) because its file-mate
  `authenticate` performs an authorization check. `load_profile` does not need that gate —
  this is the exact false positive the **gated, opt-in** framing warns about (middleware/DI
  authorize invisibly; the heuristic groups by file). It is `POTENTIAL_GAP` (review-tier) and
  off by default for this reason.

## Controls that correctly stay silent

- `authenticate` — handles every AccountStatus with a final `else`.
- `GET` (`frontend/app/api/users/route.ts`) — **cross-language scoping (#15)**: the frontend
  `AccountStatus` union is a different closed set than the Python enum (no `pending_verification`);
  the switch is exhaustive over the union and has a default, so it is not flagged against the
  Python enum's extra member.
- `AccountPage`, `middleware.ts` — a switch with a default and a lone auth guard.
- `reset_password`, `get_profile` — single-value guards (one member is a guard, not a dispatch).
- `cancel`, `request_refund` — `not in {...}` allow-list guards, excluded from positive-dispatch.

## Planted defects not yet caught (deferred, with reason)

- **#2** `reset_password` omits DELETED/PENDING — a single-value guard, intentionally not flagged
  to keep false positives low.
- **#7/#8** `cancel` (404) vs `request_refund` (409) divergent refundable set / status code — both
  are `not in` guards over different sets, sharing no `(subject, value)`; needs a future
  guard-set-divergence detector.
- **#13** `quick_order` missing the validation `create` has — a validation-divergence detector,
  still to come (def/use data-flow primitive).
