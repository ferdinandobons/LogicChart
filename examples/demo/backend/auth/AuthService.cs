namespace Auth;

public enum Role
{
    Admin,
    Member,
    Guest
}

public class AuthService
{
    public bool CanAccess(Role role, string resource)
    {
        switch (role)
        {
            case Role.Admin:
                return true;
            case Role.Member:
                return IsPublic(resource) || IsOwnedResource(resource);
            case Role.Guest:
                return false;
            default:
                return false;
        }
    }

    public string AuditDecision(Role role, string resource, bool emergency)
    {
        if (emergency && role == Role.Admin)
        {
            return "break_glass";
        }
        if (CanAccess(role, resource))
        {
            return "allow";
        }
        if (IsPublic(resource))
        {
            return "read_only";
        }
        return "deny";
    }

    private bool IsPublic(string resource)
    {
        return resource.StartsWith("public/");
    }

    private bool IsOwnedResource(string resource)
    {
        return resource.StartsWith("users/self/");
    }
}
