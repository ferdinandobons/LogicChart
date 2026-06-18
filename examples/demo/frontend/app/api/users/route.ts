import { database, User } from "../../../lib/db";
import { UserStatus } from "../../../lib/userStatus";

export async function GET(request: Request): Promise<Response> {
  const user = await loadUser(request);
  const access = resolveUserAccess(user);

  if (access === "blocked") {
    return new Response("Blocked", { status: 403 });
  }
  if (access === "gone") {
    return new Response("Deleted", { status: 410 });
  }
  return Response.json({ user, access });
}

export async function POST(request: Request) {
  const user = await loadUser(request);
  const moderation = moderationAction(user);

  if (moderation === "review") {
    await auditUser(user, "manual_review");
  }

  switch (user.status) {
    case UserStatus.ACTIVE:
      return Response.json(await activateUser(user));
    case UserStatus.SUSPENDED:
      await auditUser(user, "blocked_login");
      return new Response("Blocked", { status: 403 });
  }
}

async function loadUser(request: Request): Promise<User> {
  return database.users.find(request);
}

function resolveUserAccess(user: User): "allowed" | "limited" | "blocked" | "gone" {
  switch (user.status) {
    case UserStatus.ACTIVE:
      return user.riskScore > 80 ? "limited" : "allowed";
    case UserStatus.SUSPENDED:
      return "blocked";
    case UserStatus.DELETED:
      return "gone";
    case UserStatus.ARCHIVED:
      return "limited";
    case UserStatus.LOCKED:
      return "blocked";
    default:
      return "blocked";
  }
}

function moderationAction(user: User): "none" | "review" | "lock" {
  if (user.status === UserStatus.SUSPENDED || user.status === UserStatus.LOCKED) {
    return "lock";
  }
  if (user.status === UserStatus.ARCHIVED) {
    return "review";
  }
  if (user.riskScore > 70) {
    return "review";
  }
  if (user.region === "eu" && user.role === "viewer") {
    return "review";
  }
  return "none";
}

async function activateUser(user: User): Promise<User> {
  if (user.riskScore > 90) {
    await auditUser(user, "high_risk_active_user");
    return database.users.save({ ...user, status: UserStatus.SUSPENDED });
  }
  return database.users.save(user);
}

async function auditUser(user: User, action: string): Promise<void> {
  await database.audit.write({
    actorId: user.id,
    action,
    reason: user.status,
  });
}
