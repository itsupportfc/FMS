from tms.policies.navigation import get_sidebar_items


def layout_context(request):
    user = request.user

    if not user.is_authenticated:
        return {}

    return {
        "sidebar_items": get_sidebar_items(user),
    }
