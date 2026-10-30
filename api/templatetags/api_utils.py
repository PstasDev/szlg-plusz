from django import template

from ..utils import decide_prefix_a_or_az

register = template.Library()
register.filter(decide_prefix_a_or_az)
