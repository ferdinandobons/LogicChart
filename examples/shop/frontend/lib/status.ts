// Domain status types as known to the frontend.
// NOTE: AccountStatus intentionally omits "pending_verification" - unverified
// accounts never reach the frontend. This is a DIFFERENT closed set than the
// backend AccountStatus enum, and the two must not be conflated by cross-flow
// analysis (a cross-language false-positive control).
export type AccountStatus = "active" | "suspended" | "deleted";

export type OrderStatus =
  | "cart"
  | "placed"
  | "paid"
  | "shipped"
  | "delivered"
  | "cancelled"
  | "refunded";

export type PaymentResult = "approved" | "declined" | "pending" | "fraud_review";
