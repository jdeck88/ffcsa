import csv
import io

from django.core.mail import EmailMessage
from mezzanine.conf import settings
from django.core.management import BaseCommand
from datetime import date, timedelta, datetime

from ffcsa.core.models import Payment


class Command(BaseCommand):
    """
    """
    help = 'Send CSV of employee payments to DFF for the previous month'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            action='store',
            type=lambda s: datetime.strptime(s, '%Y-%m-%d').date(),
            default=date.today().replace(day=1) - timedelta(days=1),
            help="end date to run the payment report for the previous month"
        )

    def handle(self, *args, **options):
        end = options['date']
        start = end.replace(day=1)

        payments = Payment.objects.filter(date__gte=start, date__lte=end, is_credit=False, charge_id__isnull=False,
                                          user__is_active=True, user__profile__non_subscribing_member=True).order_by(
            'user__last_name', 'user__first_name', 'date')

        # setup the default writer
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(['Last Name', 'First Name', 'Date', 'Amount'])

        for p in payments:
            writer.writerow([p.user.last_name, p.user.first_name, p.date, p.amount, p.charge_id])

        msg = EmailMessage("Employee Payments - {}".format(start.strftime('%B %Y')), "Employee payments attached.",
                           settings.EMAIL_HOST_USER, ('info@deckfamilyfarm.com',))
        msg.attach("ffcsa_employee_payments_{}.csv".format(start.strftime('%B_%Y')), output.getvalue(),
                   mimetype='text/csv')
        msg.send()
