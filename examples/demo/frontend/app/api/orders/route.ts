import { database, Order, User } from "../../../lib/db";
import { OrderState } from "../../../lib/orderState";
import { UserStatus } from "../../../lib/userStatus";

export async function GET(request: Request): Promise<Response> {
  const order = await loadOrder(request);
  const user = await loadUser(request);

  switch (order.state) {
    case OrderState.DRAFT:
      return draftResponse(order, user);
    case OrderState.OPEN:
      return openResponse(order, user);
    case OrderState.PAID:
      return paidResponse(order, user);
    case OrderState.FRAUD_REVIEW:
      return reviewResponse(order, user);
    case OrderState.CLOSED:
      return new Response("Closed", { status: 410 });
    case OrderState.CANCELLED:
      return new Response("Cancelled", { status: 409 });
  }
}

export async function PATCH(request: Request): Promise<Response> {
  const order = await loadOrder(request);
  const user = await loadUser(request);
  const action = decideOrderAction(order, user);

  if (action === "reject") {
    await auditOrder(order, user, "rejected");
    return new Response("Order blocked", { status: 403 });
  }
  if (action === "review") {
    await auditOrder(order, user, "manual_review");
    return new Response("Review required", { status: 202 });
  }

  const saved = await applyOrderAction(order, action);
  await auditOrder(saved, user, action);
  return Response.json(saved);
}

async function loadOrder(request: Request): Promise<Order> {
  return database.orders.find(request);
}

async function loadUser(request: Request): Promise<User> {
  return database.users.find(request);
}

function draftResponse(order: Order, user: User): Response {
  if (user.role === "admin") {
    return Response.json({ order, next: "publish" });
  }
  return new Response("Draft", { status: 423 });
}

function openResponse(order: Order, user: User): Response {
  if (user.riskScore > 70) {
    return new Response("Risk review", { status: 202 });
  }
  if (order.totalCents > 50000 && user.role !== "admin") {
    return new Response("Approval required", { status: 202 });
  }
  return Response.json({ order, next: "collect_payment" });
}

function paidResponse(order: Order, user: User): Response {
  if (order.expedited && user.region === "apac") {
    return Response.json({ order, next: "expedite_international" });
  }
  if (order.expedited) {
    return Response.json({ order, next: "expedite" });
  }
  return Response.json({ order, next: "ship" });
}

function reviewResponse(order: Order, user: User): Response {
  if (user.role === "admin") {
    return Response.json({ order, next: "admin_review" });
  }
  return new Response("Manual review", { status: 202 });
}

function decideOrderAction(order: Order, user: User): "approve" | "reject" | "review" {
  if (user.status === UserStatus.SUSPENDED) {
    return "reject";
  }
  if (order.state === OrderState.FRAUD_REVIEW) {
    return "review";
  }
  if (order.totalCents > 100000 && user.role !== "admin") {
    return "review";
  }
  return "approve";
}

async function applyOrderAction(order: Order, action: "approve" | "review"): Promise<Order> {
  if (action === "review") {
    return database.orders.save({ ...order, state: OrderState.FRAUD_REVIEW });
  }
  if (order.state === OrderState.DRAFT) {
    return database.orders.save({ ...order, state: OrderState.OPEN });
  }
  return database.orders.save(order);
}

async function auditOrder(order: Order, user: User, action: string): Promise<void> {
  await database.audit.write({
    actorId: user.id,
    action,
    reason: order.state,
  });
}
