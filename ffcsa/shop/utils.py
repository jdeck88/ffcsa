from __future__ import absolute_import, unicode_literals
from future.builtins import bytes, zip, str as _str

import hmac
from decimal import Decimal
from locale import setlocale, LC_MONETARY, Error as LocaleError

try:
    from hashlib import sha512 as digest
except ImportError:
    from md5 import new as digest

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import ugettext as _

from mezzanine.conf import settings
from mezzanine.utils.importing import import_dotted_path


def make_choices(choices):
    """
    Zips a list with itself for field choices.
    """
    return list(zip(choices, choices))


def clear_session(request, *names):
    """
    Removes values for the given session variables names
    if they exist.
    """
    for name in names:
        try:
            del request.session[name]
        except KeyError:
            pass


def recalculate_remaining_budget(request):
    """
    utility function to attach the remaining budget as an attribute on the request.user

    This should be called after any cart modifications, as we take into account the request.cart.total_price()
    in the calculated remaining_budget
    """
    from ffcsa.shop.models import Order
    from ffcsa.core.models import Payment

    if not request.user.is_authenticated():
        return

    ytd_contrib = Payment.objects.total_for_user(request.user)
    ytd_ordered = Order.objects.total_for_user(request.user)
    if not ytd_ordered:
        ytd_ordered = Decimal(0)
    if not ytd_contrib:
        ytd_contrib = Decimal(0)

    # update remaining_budget
    request.session["remaining_budget"] = float(
        "{0:.2f}".format(ytd_contrib - ytd_ordered - request.cart.total_price()))


def recalculate_cart(request):
    """
    Updates an existing discount code, shipping, and tax when the
    cart is modified.
    """
    from ffcsa.shop import checkout
    from ffcsa.shop.forms import DiscountForm
    from ffcsa.shop.models import Cart

    # Rebind the cart to request since it's been modified.
    if request.session.get('cart') != request.cart.pk:
        request.session['cart'] = request.cart.pk
    request.cart = Cart.objects.from_request(request)

    discount_code = request.session.get("discount_code", "")
    if discount_code:
        # Clear out any previously defined discount code
        # session vars.
        names = ("free_shipping", "discount_code", "discount_total")
        clear_session(request, *names)
        discount_form = DiscountForm(request, {"discount_code": discount_code})
        if discount_form.is_valid():
            discount_form.set_discount()

    # This has to happened after discount_form.set_discount() b/c that will clear the shipping variables
    if request.user.is_authenticated:
        if request.user.profile.home_delivery:
            set_home_delivery(request)
        else:
            clear_shipping(request)

    def handler(s):
        return import_dotted_path(s) if s else lambda *args: None

    billship_handler = handler(settings.SHOP_HANDLER_BILLING_SHIPPING)
    tax_handler = handler(settings.SHOP_HANDLER_TAX)
    try:
        if request.session["order"]["step"] >= checkout.CHECKOUT_STEP_FIRST:
            billship_handler(request, None)
            tax_handler(request, None)
    except (checkout.CheckoutError, ValueError, KeyError):
        pass
    recalculate_remaining_budget(request)


def set_home_delivery(request):
    if not settings.HOME_DELIVERY_ENABLED:
        return
    fee = 0 if 'free_shipping' in request.session and request.session[
        "free_shipping"] is True else request.cart.delivery_fee()
    set_shipping(request, "Home Delivery", fee)


def clear_shipping(request):
    if "shipping_type" in request.session:
        del request.session["shipping_type"]
    if "shipping_total" in request.session:
        del request.session["shipping_total"]


def set_shipping(request, shipping_type, shipping_total):
    """
    Stores the shipping type and total in the session.
    """
    request.session["shipping_type"] = _str(shipping_type)
    request.session["shipping_total"] = _str(shipping_total)


def set_tax(request, tax_type, tax_total):
    """
    Stores the tax type and total in the session.
    """
    request.session["tax_type"] = _str(tax_type)
    request.session["tax_total"] = _str(tax_total)


def sign(value):
    """
    Returns the hash of the given value, used for signing order key stored in
    cookie for remembering address fields.
    """
    key = bytes(settings.SECRET_KEY, encoding="utf8")
    value = bytes(value, encoding="utf8")
    return hmac.new(key, value, digest).hexdigest()


def set_locale():
    """
    Sets the locale for currency formatting.
    """
    currency_locale = str(settings.SHOP_CURRENCY_LOCALE)
    try:
        if setlocale(LC_MONETARY, currency_locale) == "C":
            # C locale doesn't contain a suitable value for "frac_digits".
            raise LocaleError
    except LocaleError:
        msg = _("Invalid currency locale specified for SHOP_CURRENCY_LOCALE: "
                "'%s'. You'll need to set the locale for your system, or "
                "configure the SHOP_CURRENCY_LOCALE setting in your settings "
                "module.")
        raise ImproperlyConfigured(msg % currency_locale)


def recalculate_product_price(price):
    """
    Icrease product's price by QUICK_CHECKOUT_INCREASE
    """
    QUICK_CHECKOUT_INCREASE = Decimal('.05')
    return round(Decimal(price) + Decimal(price) * QUICK_CHECKOUT_INCREASE, 2)

