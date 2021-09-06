from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand
from django.db.models import Q, Max
from django.conf import settings
from django.utils import formats

from ffcsa.core import sendinblue
from ffcsa.core.models import Payment
from ffcsa.shop.models import Order
from ffcsa.shop.orders import get_order_period_for_user

User = get_user_model()


class Command(BaseCommand):
    help = 'Send an email to all users who are no longer engaged/active'

    def handle(self, *args, **options):
        three_weeks_ago = (datetime.now() - timedelta(days=21)).date()
        six_weeks_ago = (datetime.now() - timedelta(days=42)).date()
        thirteen_weeks_ago = (datetime.now() - timedelta(days=91)).date()
        twenty_six_weeks_ago = (datetime.now() - timedelta(days=182)).date()
        one_year_ago = (datetime.now() - timedelta(days=365)).date()
        fourteen_days = (datetime.now() - timedelta(days=14)).date()

        # All users that have joined more then 2 weeks ago, have non_subscribing_member=False,
        # do not have a strip_subscription_id, and are still marked as active
        # 3, 6, 13, 26, 52 week reminder sequence
        users_with_non_recent_orders = Order.objects.values('user_id').annotate(latest_order=Max('time')).filter(
            (Q(lastest_order_gt=three_weeks_ago) & Q(latest_order_lte=three_weeks_ago + timedelta(days=7))) |
            (Q(lastest_order_gt=six_weeks_ago) & Q(latest_order_lte=six_weeks_ago + timedelta(days=7))) |
            (Q(lastest_order_gt=thirteen_weeks_ago) & Q(latest_order_lte=thirteen_weeks_ago + timedelta(days=7))) |
            (Q(lastest_order_gt=twenty_six_weeks_ago) & Q(latest_order_lte=twenty_six_weeks_ago + timedelta(days=7))) |
            (Q(lastest_order_gt=one_year_ago) & Q(latest_order_lte=one_year_ago + timedelta(days=7)))
        ).values_list('user_id', flat=True)

        non_engaged_users = User.objects.filter(
            id__in=users_with_non_recent_orders,
            profile__non_subscribing_member=False,
            is_active=True,
            date_joined__lt=fourteen_days
        ) \
            .exclude(username=settings.FEED_A_FRIEND_USER)

        for user in non_engaged_users:
            ytd_contrib = Payment.objects.total_for_user(user)
            ytd_ordered = Order.objects.total_for_user(user)
            if not ytd_ordered:
                ytd_ordered = Decimal(0)
            if not ytd_contrib:
                ytd_contrib = Decimal(0)

            remaining_budget = ytd_contrib - ytd_ordered

            if settings.SENDINBLUE_ENABLED and remaining_budget > 30:
                # send reminder
                week_start, week_end = get_order_period_for_user(user)
                order_period = "{} at {} through midnight on {}".format(
                    formats.date_format(week_start, "D F d"),
                    formats.date_format(week_start, "P"),
                    formats.date_format(week_end, "D F d")
                )

                params = {'FIRSTNAME': user.first_name, 'ORDERWINDOW': order_period}
                email_result = sendinblue.send_transactional_email(
                    'Non Engaged Member', user.email,
                    params)

                if email_result is False:
                    raise Exception("Failed to send {} non engagement email".format(user))
