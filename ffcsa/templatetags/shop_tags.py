from __future__ import unicode_literals

from django.utils import formats
from future.builtins import str

from decimal import Decimal
import locale
import platform

from django import template

from ffcsa.shop.orders import get_order_period_for_user, valid_order_period_for_user
from ffcsa.shop.utils import set_locale

register = template.Library()


@register.simple_tag(takes_context=True)
def order_period_end(context):
    period_start, period_end = get_order_period_for_user(context.request.user)
    date = formats.date_format(period_end, "l, F jS")
    time = formats.date_format(period_end, "P")
    return date + " at " + time


@register.simple_tag(takes_context=True)
def order_period_start(context):
    period_start, period_end = get_order_period_for_user(context.request.user)
    date = formats.date_format(period_start, "l, F jS")
    time = formats.date_format(period_start, "P")
    return date + " at " + time


@register.simple_tag(takes_context=True)
def is_order_cycle(context):
    if context.request.user.is_authenticated():
        return valid_order_period_for_user(context.request.user)
    else:
        return True


@register.filter
def product_has_stock(product):
    if not product:
        return False

    return any(v.has_stock() for v in product.variations.all())


@register.filter
def currency(value):
    """
    Format a value as currency according to locale.
    """
    set_locale()
    if not value:
        value = 0
    value = locale.currency(Decimal(value), grouping=True)
    if platform.system() == 'Windows':
        try:
            value = str(value, encoding=locale.getpreferredencoding())
        except TypeError:
            pass
    return value


def _order_totals(context):
    """
    Add shipping/tax/discount/order types and totals to the template
    context. Use the context's completed order object for email
    receipts, or the cart object for checkout.
    """
    fields = ["shipping_type", "shipping_total", "discount_total",
              "tax_type", "tax_total"]
    template_vars = {}

    if "order" in context:
        for field in fields + ["item_total"]:
            template_vars[field] = getattr(context["order"], field)
    else:
        template_vars["item_total"] = context["request"].cart.item_total_price()
        if context["request"].user.is_authenticated and context["request"].user.profile.home_delivery:
            template_vars["shipping_type"] = "Home Delivery"
            template_vars["shipping_total"] = context["request"].cart.delivery_fee()
        if template_vars["item_total"] == 0:
            # Ignore session if cart has no items, as cart may have
            # expired sooner than the session.
            template_vars["tax_total"] = 0
            template_vars["discount_total"] = 0
            template_vars["shipping_total"] = 0
        else:
            for field in fields:
                template_vars[field] = context["request"].session.get(
                    field, None)
    template_vars["order_total"] = template_vars.get("item_total", None)
    if template_vars.get("shipping_total", None) is not None:
        template_vars["order_total"] += Decimal(
            str(template_vars["shipping_total"]))
    if template_vars.get("discount_total", None) is not None:
        template_vars["order_total"] -= Decimal(
            str(template_vars["discount_total"]))
    if template_vars.get("tax_total", None) is not None:
        template_vars["order_total"] += Decimal(
            str(template_vars["tax_total"]))
    return template_vars


@register.inclusion_tag("shop/includes/order_totals.html", takes_context=True)
def order_totals(context):
    """
    HTML version of order_totals.
    """
    return _order_totals(context)


@register.inclusion_tag("shop/includes/order_totals.txt", takes_context=True)
def order_totals_text(context):
    """
    Text version of order_totals.
    """
    return _order_totals(context)
