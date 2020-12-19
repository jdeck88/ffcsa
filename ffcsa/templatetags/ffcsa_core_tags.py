import datetime

import bleach
from django.template.loader import get_template
from django import forms
from django.utils import formats
from django.utils.safestring import mark_safe
from mezzanine import template

from ffcsa.core.dropsites import get_pickup_date

register = template.Library()


@register.simple_tag(takes_context=True)
def pickup_date_text(context):
    user = context['request'].user
    pickup = get_pickup_date(user)

    return "{} for pickup or delivery on {}".format("Weekly order" if user.profile.is_subscribing_member else "Order",
                                                    formats.date_format(pickup, "l, F jS"))


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def get_attr(value, arg):
    return getattr(value, arg)


@register.filter
def sum_items(items):
    total = 0
    for i in items:
        total = total + i['total_price']
    return total


@register.filter
def get_billing_detail_field(billing_detail_list, key):
    for (k, value) in billing_detail_list:
        if k == key:
            return value

    return None


@register.filter
def is_checkbox(boundfield):
    """Return True if this field's widget is a CheckboxInput."""
    return isinstance(boundfield.field.widget, forms.CheckboxInput)


@register.filter
def is_select(boundfield):
    """Return True if this field's widget is a CheckboxInput."""
    return isinstance(boundfield.field.widget, forms.Select)


@register.simple_tag(takes_context=True)
def render_field(context, field, **kwargs):
    """
    Renders a single form field
    """
    template = kwargs.get('template', "includes/form_field.html")
    # This will make a copy of the context so it isn't globally modified
    c = context.flatten()
    c["field"] = field
    if 'show_required' not in c:
        c["show_required"] = True
    if 'show_label' not in c:
        c["show_label"] = True
    c.update(kwargs)
    return get_template(template).render(c)


@register.filter
def truncate(value, length):
    if not value:
        return value
    elif len(value) <= length:
        return mark_safe(value)

    # don't truncate in the middle of a word
    s = bleach.clean(value[:length], strip=True)
    while not s[-1] in [' ', '\n']:
        s = s[:-1]

    return s + ' ...'
