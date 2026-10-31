from django.shortcuts import render


_DASHBOARD_PATH_PREFIXES = (
    "/dashboard/",
    "/account/",
    "/security/",
    "/apps/",
    "/grants/",
    "/admin/user-import/",
    "/admin/manual-review/",
)


def page_not_found(request, exception):
    """Render a 404 in the signed-in dashboard or public portal layout."""
    user = getattr(request, "user", None)
    is_dashboard_request = request.path.startswith(_DASHBOARD_PATH_PREFIXES)
    if getattr(user, "is_authenticated", False) and is_dashboard_request:
        template_name = "dashboard/404.html"
    else:
        template_name = "portal/404.html"
    return render(request, template_name, status=404)
