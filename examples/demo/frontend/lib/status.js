// Human-readable label for a user status. Unlike the API route, this helper
// handles every status including "deleted", so it never falls through.
export function statusLabel(status) {
  switch (status) {
    case "active":
      return "Active";
    case "suspended":
      return "Suspended";
    case "deleted":
      return "Deleted";
    case "archived":
      return "Archived";
    case "locked":
      return "Locked";
    default:
      return "Unknown";
  }
}

export function statusTone(status) {
  switch (status) {
    case "active":
      return "success";
    case "suspended":
      return "warning";
    case "deleted":
      return "danger";
    case "archived":
      return "neutral";
    case "locked":
      return "danger";
    default:
      return "neutral";
  }
}
