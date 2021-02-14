from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand
from django.db.models import Q
from django.conf import settings

from ffcsa.core.models import Payment
from ffcsa.core.sendinblue import on_user_cancel_subscription
from ffcsa.shop.models import Order


class Command(BaseCommand):
    help = 'Deactivate all users who are no longer engaged/active'

    def handle(self, *args, **options):
        two_months_date = (datetime.now() - timedelta(days=60)).date()
        fourteen_days = (datetime.now() - timedelta(days=14)).date()

        # All users that have joined more then 2 weeks ago, have non_subscribing_member=False,
        # do not have a strip_subscription_id, and are still marked as active
        potential_inactive_users = get_user_model().objects.filter(
            Q(profile__stripe_subscription_id__isnull=True) |
            Q(profile__stripe_subscription_id__exact=''),
            is_active=True,
            profile__non_subscribing_member=False,
            date_joined__lt=fourteen_days) \
            .exclude(username=settings.FEED_A_FRIEND_USER)

        # These users are potentially inactive
        for user in potential_inactive_users:
            ytd_contrib = Payment.objects.total_for_user(user)
            ytd_ordered = Order.objects.total_for_user(user)
            if not ytd_ordered:
                ytd_ordered = Decimal(0)
            if not ytd_contrib:
                ytd_contrib = Decimal(0)

            remaining_budget = ytd_contrib - ytd_ordered
            last_order = Order.objects.all_for_user(user).order_by('-time').first()

            # If the user has less then $20 remaining and the
            if last_order is None or (remaining_budget < 10 and last_order.time.date() < two_months_date):
                user.is_active = False
                on_user_cancel_subscription(user)
                user.save()
                print('Deactivating user: {}'.format(user))
