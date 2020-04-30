import datetime

from ffcsa import settings
from ffcsa.core.dropsites import is_valid_dropsite


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

    return True


def valid_order_period_for_user(user):
    if user.profile.home_delivery:
        return _home_delivery_can_order(user)

    for window in settings.ORDER_WINDOWS:
        if user.profile.drop_site in window['dropsites']:
            return _is_order_window(window)

    return False


def get_order_period_for_user(user):
    window = None
    if user.profile.home_delivery:
        zip = user.profile.get_delivery_zip()

        for window in settings.ORDER_WINDOWS:
            if zip in window['homeDeliveryZips']:
                break

    else:
        for window in settings.ORDER_WINDOWS:
            if user.profile.drop_site in window['dropsites']:
                break

    if window is not None:
        return _get_order_window_start(window), _get_order_window_end(window)

    return None, None


def _home_delivery_can_order(user):
    zip = user.profile.get_delivery_zip()

    for window in settings.ORDER_WINDOWS:
        if zip in window['homeDeliveryZips']:
            return _is_order_window(window)

    return False


def _is_order_window(window):
    return _get_order_window_start(window) <= datetime.datetime.now() <= _get_order_window_end(window)


def _get_order_window_start(window):
    week_end = _get_order_window_end(window)
    week_start = _get_next_day(window['startDay'])

    if week_start >= week_end:
        week_start = week_start - datetime.timedelta(7)

    hour, minute = window['startTime'].split(':')
    return week_start.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def _get_order_window_end(window):
    week_end = _get_next_day(window['endDay'])
    hour, minute = window['endTime'].split(':')
    return week_end.replace(hour=int(hour), minute=int(minute), second=59, microsecond=0)


def _get_next_day(day):
    """
    Returns a datetime in the future for the next day number (1 - 7 (Mon - Sun))
    """
    now = datetime.datetime.now()

    if now.isoweekday() <= day:
        delta = day - now.isoweekday()
    else:
        delta = 7 - (now.isoweekday() - day)
    return now + datetime.timedelta(delta)
