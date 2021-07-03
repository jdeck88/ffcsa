from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand

from ffcsa.core.models import Payment
from ffcsa.management.commands.deactivate_non_engaged_users import donate_proceeds
from ffcsa.shop.models import Order


class Command(BaseCommand):
    help = 'Donate remaining budget for all inactive users'

    def handle(self, *args, **options):
        inactive_users = get_user_model().objects.filter(is_active=False)

        # These users are potentially inactive
        for user in inactive_users:
            ytd_contrib = Payment.objects.total_for_user(user)
            ytd_ordered = Order.objects.total_for_user(user)
            if not ytd_ordered:
                ytd_ordered = Decimal(0)
            if not ytd_contrib:
                ytd_contrib = Decimal(0)

            remaining_budget = ytd_contrib - ytd_ordered
            if remaining_budget > 0:
                donate_proceeds(remaining_budget, user)
                print('Donating remaining budget from user: {} - {}'.format(user, remaining_budget))
