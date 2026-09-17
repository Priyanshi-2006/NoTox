from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """
    Checks the application-level `role` field, not Django's is_staff.
    Not used by any Stage 1 endpoint yet — this is the extension point
    the admin dashboard stage will import instead of re-deriving its
    own role check.
    """

    message = "This action requires an admin role."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_admin
        )


class IsModeratorRole(BasePermission):
    """
    Checks if the user has moderator or admin privileges.
    """

    message = "This action requires a moderator or admin role."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_moderator
        )



class IsNotRestricted(BasePermission):
    """
    Extension point for the strikes/restrictions stage. Stage 1 does not
    enforce restrictions anywhere, but posting/commenting/chat endpoints
    in later stages should depend on this rather than re-implementing
    the check.
    """

    message = "Your account is currently restricted."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and not request.user.is_restricted
        )
