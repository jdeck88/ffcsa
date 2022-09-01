from django.core.mail import send_mail
from django.db import connection
from mezzanine.conf import settings
from django.core.management import BaseCommand
from datetime import date, timedelta


class Command(BaseCommand):
    """
    """
    help = 'Report how many totes were delivered for the past month excluding today'

    def handle(self, *args, **options):
        today = date.today()

        yesterday = today - timedelta(days=1)
        # last_day_of_previous_month = yesterday.replace(day=1) - timedelta(days=1)
        one_month_ago = today.replace(month=yesterday.month, year=yesterday.year)

        total = 0
        dff_dropsites = [d['name'] for d in settings.DROPSITES if d.get('DFFDelivery', False)]

        with connection.cursor() as cursor:
            query = """
                select drop_site, count(*) 
                from shop_order 
                where time >= '{}' and time <= '{}' and drop_site <> '' 
                group by drop_site
                """.format(one_month_ago, yesterday)
            cursor.execute(query)

            results = cursor.fetchall()

        msg = "Orders delivered by dropsite between {} and {}:\n\n".format(one_month_ago.strftime('%b %d, %Y'),
                                                                       yesterday.strftime('%b %d, %Y'))

        for dropsite, num_of_orders in results:
            if dropsite in dff_dropsites:
                total = total + num_of_orders
            msg = msg + "{}\t{}\n".format(num_of_orders, dropsite)

        msg = msg + "\n{}\ttotal orders DFF delivered to dropsites: {}".format(total, ", ".join(dff_dropsites))

        send_mail(
            'DFF Deliveries',
            msg,
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_FROM_EMAIL],
            fail_silently=False,
        )
