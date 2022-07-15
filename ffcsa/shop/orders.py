import datetime

from ffcsa import settings
from ffcsa.core.dropsites import is_valid_dropsite
from ffcsa.core.utils import get_next_day


def user_can_order(user):
    # TODO fix this for one-time orders
    if not user.is_authenticated():
        return False, "You must be authenticated in order to add products to your cart"

    if not user.profile.signed_membership_agreement:
        return False, "You must sign our membership agreement before you can make an order"

    if not is_valid_dropsite(user):
        return False, "Your current dropsite is no longer available. " \
                      "Please select a different dropsite before adding items to your cart."

    if not valid_order_period_for_user(user):
        return False, "Your order period has not opened."

    return True, ""


def valid_order_period_for_user(user):
    if user.profile.home_delivery:
        return _home_delivery_can_order(user)

    for window in settings.ORDER_WINDOWS:
        if user.profile.drop_site in window['dropsites']:
            return _is_order_window(window)

    return False


def get_order_window_for_user(user):
    zip = user.profile.delivery_address.zip if user.profile.home_delivery else None
    drop_site = user.profile.drop_site if not user.profile.home_delivery else None
    return get_order_window(drop_site, zip)


def get_order_window(drop_site=None, zip=None):
    if drop_site is None and zip is None:
        raise Exception('Either drop_site or zip is required')

    window = None
    if zip:
        for window in settings.ORDER_WINDOWS:
            if zip in window['homeDeliveryZips']:
                break

    else:
        for window in settings.ORDER_WINDOWS:
            if drop_site in window['dropsites']:
                break

    return window


def get_order_period(drop_site=None, zip=None):
    window = get_order_window(drop_site, zip)

    if window is not None:
        return _get_order_window_start(window), _get_order_window_end(window)

    return None, None


def get_order_period_for_user(user):
    profile = user.profile
    zip = profile.delivery_address.zip if profile.delivery_address and profile.home_delivery else None
    drop_site = profile.drop_site if not profile.home_delivery else None
    return get_order_period(drop_site, zip)


def _home_delivery_can_order(user):
    zip = user.profile.delivery_address.zip

    for window in settings.ORDER_WINDOWS:
        if zip in window['homeDeliveryZips']:
            return _is_order_window(window)

    return False


def _is_order_window(window):
    return _get_order_window_start(window) <= datetime.datetime.now() <= _get_order_window_end(window)


def _get_order_window_start(window):
    week_end = _get_order_window_end(window)
    week_start = get_next_day(window['startDay'])

    if week_start >= week_end:
        week_start = week_start - datetime.timedelta(7)

    hour, minute = window['startTime'].split(':')
    return week_start.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def _get_order_window_end(window):
    week_end = get_next_day(window['endDay'])
    hour, minute = window['endTime'].split(':')
    return week_end.replace(hour=int(hour), minute=int(minute), second=59, microsecond=0)
