export default function UsersPage({ user }: Props) {
  if (user.isLoading) {
    return <LoadingSkeleton />;
  }

  if (user.error) {
    return <ErrorState error={user.error} />;
  }

  if (!user.isAuthorized) {
    return <LoginPrompt />;
  }

  if (user.status === "deleted") {
    return <DeletedAccount />;
  }

  if (user.status === "suspended") {
    return <SuspendedAccount user={user} />;
  }

  if (user.status === "archived") {
    return <ArchivedAccount user={user} />;
  }

  if (user.status === "locked") {
    return <LockedAccount user={user} />;
  }

  return <UserDashboard user={user} mode={dashboardMode(user)} />;
}

function dashboardMode(user: Props["user"]) {
  if (user.role === "admin") {
    return "admin";
  }
  if (user.flags.includes("beta")) {
    return "beta";
  }
  return "standard";
}

function UserDashboard({ user, mode }) {
  if (mode === "admin") {
    return <AdminDashboard user={user} />;
  }
  if (mode === "beta") {
    return <BetaDashboard user={user} />;
  }
  return <StandardDashboard user={user} />;
}
