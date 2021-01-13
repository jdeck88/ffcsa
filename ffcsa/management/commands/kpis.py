from django.core.mail import send_mail
from django.db import connection
from mezzanine.conf import settings
from django.core.management import BaseCommand
from datetime import date, timedelta, datetime


class Command(BaseCommand):
    """
    """
    help = 'Calculate KPIs for the past month excluding today'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            action='store',
            type=lambda s: datetime.strptime(s, '%Y-%m-%d').date(),
            default=date.today(),
            help="Send orders to vendors"
        )

    def handle(self, *args, **options):
        date = options['date']

        yesterday = date - timedelta(days=1)
        last_day_of_previous_month = yesterday.replace(day=1) - timedelta(days=1)
        one_month_ago = date.replace(month=last_day_of_previous_month.month, year=last_day_of_previous_month.year)
        jan_first = date.replace(month=1, day=1, year=last_day_of_previous_month.year)

        # excluded users are farmily, ewing, lopez, albarquoni
        excluded_users = '1, 13, 24, 61'

        with connection.cursor() as cursor:
            # average $ / order over the last month
            query = """
                select avg(total)
                from shop_order 
                where date(time) in ( select * from (
                    select date(time) 
                    from shop_order
                    where time >= '{}' and time <= '{}' and user_id not in ({})
                    group by date(time) having count(1) > 4
                 ) as a)  
                """
            cursor.execute(query.format(one_month_ago, yesterday, excluded_users))
            avg_order_last_month = cursor.fetchall()[0][0]
            cursor.execute(
                query.format(one_month_ago - timedelta(days=365), yesterday - timedelta(days=365), excluded_users))
            avg_order_last_month_last_year = cursor.fetchall()[0][0]

            # average $ / order YTD
            cursor.execute(query.format(jan_first, yesterday, excluded_users))
            avg_order_ytd = cursor.fetchall()[0][0]
            cursor.execute(
                query.format(jan_first - timedelta(days=365), yesterday - timedelta(days=365), excluded_users))
            avg_order_ytd_last_year = cursor.fetchall()[0][0]

            # of engaged members over the past month
            query = """
                select count(distinct(user_id)) 
                from shop_order 
                where time >= '{}' and time <= '{}' and user_id is not null
                """
            cursor.execute(query.format(one_month_ago, yesterday))
            number_of_engaged_members = cursor.fetchall()[0][0]
            cursor.execute(query.format(one_month_ago - timedelta(days=365), yesterday - timedelta(days=365)))
            number_of_engaged_members_last_year = cursor.fetchall()[0][0]

            # of members
            query = """
                select count(user_id) 
                from ffcsa_core_profile 
                join auth_user u on u.id = user_id 
                where is_active = true;
            """
            cursor.execute(query)
            number_of_members = cursor.fetchall()[0][0]

            # of active subscriptions
            query = """
                select count(user_id) 
                from ffcsa_core_profile 
                where stripe_subscription_id is not null and stripe_subscription_id <> '';
            """
            cursor.execute(query)
            number_of_subscriptions = cursor.fetchall()[0][0]

        msg = """
        Date: {}
        The following KPIs are for the past month.
        
        Avg $ / order: ${}
        Avg $ / order YTD: ${}
        Avg $ / order last year: ${}
        Avg $ / order YTD last year: ${}
        # of engaged members: {}
        # of engaged members last year: {}
        # of members: {}
        # of subscriptions: {}
        """.format(yesterday, avg_order_last_month, avg_order_ytd, avg_order_last_month_last_year,
                   avg_order_ytd_last_year, number_of_engaged_members, number_of_engaged_members_last_year,
                   number_of_members, number_of_subscriptions)

        print(msg)
        send_mail(
            'Monthly KPIs',
            msg,
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_FROM_EMAIL],
            fail_silently=False,
        )
