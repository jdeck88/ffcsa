from decimal import Decimal
from django.db.models import Sum, Manager

from ffcsa.settings import YEARLY_SUBSCRIBER_MINIMUM


class PaymentManager(Manager):
    def is_yearly_subscriber(self, user):
        return self.filter(user=user, amount__gte=YEARLY_SUBSCRIBER_MINIMUM).count() > 0

    def total_for_user(self, user):
        total = self \
            .filter(user=user, status__in=['Accepted', 'Failed']) \
            .aggregate(total=Sum('amount'))['total']

        if total is None:
            total = Decimal(0)

        return total
