from django import template

from ..scopes import describe_scopes

register = template.Library()


@register.filter
def scope_details(scopes):
    return describe_scopes(scopes or [])
