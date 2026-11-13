from rest_framework.permissions import BasePermission


class IsStaffMember(BasePermission):
    """Any active panel account.

    The task board is deliberately readable by every staff member, with no
    capability required: the point of the section is that people can see what
    the team is carrying and who has it. Writing is narrower - creating and
    assigning need manage_tasks, and completing is restricted to your own
    assignment by the view.
    """

    message = "This section is for staff accounts."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_staff)
