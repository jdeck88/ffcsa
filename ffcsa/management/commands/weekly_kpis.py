from django.core.mail import send_mail
from django.db import connection
from mezzanine.conf import settings
from django.core.management import BaseCommand
from datetime import date, timedelta, datetime
from dateutil import relativedelta

from ffcsa.shop.models import OrderItem


class Command(BaseCommand):
    """
    """
    help = 'Calculate KPIs for the past week'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            action='store',
            type=lambda s: datetime.strptime(s, '%Y-%m-%d').date(),
            default=date.today(),
        )

    def handle(self, *args, **options):
        date = options['date']

        today = date
        start = today - timedelta((today.weekday() + 1) % 7)
        last_sun = start + relativedelta.relativedelta(weekday=relativedelta.SU(0))
        last_mon = last_sun - timedelta(6)

        # excluded users are farmily, ewing, lopez, feed-a-friend, albarquoni
        excluded_users = '1, 13, 24, 44, 61'

        with connection.cursor() as cursor:
            # total sales, & order #'s last month
            query = """
                select sum(total), count(id)
                from shop_order 
                where date(time) in ( select * from (
                    select date(time) 
                    from shop_order
                    where time >= '{}' and time <= '{}' and user_id not in ({})
                    group by date(time) having count(1) > 4
                 ) as a)  
                """
            cursor.execute(query.format(last_mon, last_sun, excluded_users))
            results = cursor.fetchall()[0]
            total_sales = results[0]
            num_orders = results[1]

            # total garden sales
            query = """
                select sum(vendor_price * quantity)
                from shop_orderitem
                where order_id in ( select * from (
                    select id
                    from shop_order
                    where time >= '{}' and time <= '{}' and user_id not in ({})
                 ) as a) and lower(vendor) like '%graz%garden%'
                """
            cursor.execute(query.format(last_mon, last_sun, excluded_users))
            results = cursor.fetchall()[0]
            total_garden_sales = results[0]

            # total credits
            query = """
                select sum(amount)
                from ffcsa_core_payment
                where date >= '{}' and date <= '{}' and user_id not in ({}) and is_credit = true
                """
            cursor.execute(query.format(last_mon, last_sun, excluded_users))
            results = cursor.fetchall()[0]
            total_credits = results[0]

        msg = """
        Here's the KPI report for the week of {} - {}.
        
        Total Sales:             ${}
        Total Garden Sales:      ${}
        Total Credits Issued:    ${}
        # of Orders:             {}
        """.format(last_mon.strftime('%m/%d/%Y'), last_sun.strftime('%m/%d/%Y'), total_sales, total_garden_sales, total_credits, num_orders)

        print(msg)
        send_mail(
            'Weekly KPIs {} - {}'.format(last_mon.strftime('%m/%d/%Y'), last_sun.strftime('%m/%d/%Y')),
            msg,
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_FROM_EMAIL],
            fail_silently=False,
        )
