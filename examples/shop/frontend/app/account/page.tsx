import { AccountStatus } from "../../lib/status";

// Control: a switch with an explicit default - not flagged.
export default function AccountPage({ account }: { account: { status: AccountStatus } }) {
  switch (account.status) {
    case "active":
      return <Dashboard />;
    case "suspended":
      return <SuspendedNotice />;
    default:
      return <LockedNotice />;
  }
}
