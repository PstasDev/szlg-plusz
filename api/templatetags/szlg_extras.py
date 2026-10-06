from django import template

from ..scopes import describe_scopes

register = template.Library()


@register.filter
def scope_details(scopes):
    if isinstance(scopes, str):
        scopes = scopes.split()
    return describe_scopes(scopes or [])
