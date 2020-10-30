import datetime

from django.conf import settings
from django.db.models import Sum, OuterRef, Subquery, IntegerField
from django.utils import formats
from mezzanine.utils.email import send_mail_template

from ffcsa.core.dropsites import get_pickup_date
from ffcsa.core.utils import get_current_friday_pickup_date
from ffcsa.shop.models import Cart, Order, ProductVariation, CartItem
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.core.management import BaseCommand
from django.utils.timezone import now


class Command(BaseCommand):
    """
    take all carts, and create orders out of the cart.
    This is meant to be run as a cron job, to close the current weeks order
    """
    help = 'Convert current carts into orders'

    def handle(self, *args, **options):
        carts = Cart.objects.all()

        extra_items = ProductVariation.objects \
            .filter(extra__gt=0, id__in=CartItem.objects.values('variation_id').distinct()) \
            .annotate(total_ordered=Subquery(
            CartItem.objects
                .filter(variation_id=OuterRef('pk'))
                .values('variation_id')  # provides group by variation_id
                .annotate(total_ordered=Sum('vendors__quantity'))
                .values('total_ordered'),
            output_field=IntegerField(),
        ))

        extra_items = list(extra_items)
        if len(extra_items) > 0:
            order = Order(**{
                # add 1 day since all billing is based off of Friday ordering, but orders close on Thursday
                'time': now() + datetime.timedelta(days=1),
                'site': Site.objects.get(id=1),
                'billing_detail_first_name': 'FFCSA Extra Order',
                'allow_substitutions': True
            })
            # order.save()

            has_extra = False
            total = 0
            # We do the following b/c we want to use the logic in CartItem.update_quantity to
            # determine which vendor to order the extra from
            cart, created = Cart.objects.get_or_create(user_id=0)
            cart.clear()
            for variation in extra_items:
                extra = round(variation.extra / 100 * variation.total_ordered)

                if extra > 0:
                    has_extra = True
                    if not order.id:
                        order.save()
                    item = CartItem.objects.create(cart=cart, variation=variation)
                    item.update_quantity(extra)
                    order.items.create_from_cartitem(item)
                    total += item.total_price

            if has_extra:
                order.item_total = total
                order.total = total
                order.save()
            cart.delete()

        for cart in carts:
            if cart.has_items():
                print("cart has items")
                user = get_user_model().objects.get(id=cart.user_id)

                if not user.profile.start_date:
                    user.profile.start_date = now()

                # We subtract 7 days b/c the order window has closed and get_pickup_date will return the date of
                # pickup for the next order window
                pickup_date = get_pickup_date(user) - datetime.timedelta(7)
                pickup = formats.date_format(pickup_date, "D F d")

                drop_site = user.profile.drop_site
                if user.profile.home_delivery:
                    drop_site = 'Home Delivery - {}'.format(formats.date_format(pickup_date, "D"))
                if cart.attending_dinner:
                    drop_site = 'Farm'

                order_dict = {
                    'user_id': user.id,
                    # add 1 day since all billing is based off of Friday ordering, but orders close on Thursday
                    'time': now() + datetime.timedelta(days=1),
                    'site': Site.objects.get(id=1),
                    'billing_detail_first_name': user.first_name,
                    'billing_detail_last_name': user.last_name,
                    'billing_detail_email': user.email,
                    'billing_detail_phone': user.profile.phone_number,
                    'billing_detail_phone_2': user.profile.phone_number_2,
                    'item_total': cart.item_total_price(),
                    'discount_code': user.profile.discount_code.code if user.profile.discount_code else "",
                    'discount_total': cart.discount(),
                    'total': cart.total_price(),
                    'attending_dinner': cart.attending_dinner,
                    'drop_site': drop_site,
                    'additional_instructions': user.profile.invoice_notes,
                    'plastic_bags': user.profile.plastic_bags,
                    'allow_substitutions': user.profile.allow_substitutions,
                }

                if user.profile.home_delivery:
                    delivery_address = user.profile.delivery_address
                    order_dict.update(**{
                        'shipping_type': 'Home Delivery',
                        'shipping_total': cart.delivery_fee(),
                        'shipping_detail_street': delivery_address.street,
                        'shipping_detail_city': delivery_address.city,
                        'shipping_detail_state': delivery_address.state,
                        'shipping_detail_postcode': delivery_address.zip,
                        'shipping_instructions': user.profile.delivery_notes,
                    })

                order = Order.objects.create(**order_dict)
                order.save()

                for item in cart:
                    if not item.variation.weekly_inventory:
                        item.variation.reduce_stock(item.quantity)

                    order.items.create_from_cartitem(item)

                order.save()

                sub_pickup = 'for home delivery' if user.profile.home_delivery else 'for pickup at: {}'.format(
                    user.profile.drop_site)
                send_mail_template(
                    "FFCSA Order Confirmation {}".format(sub_pickup),
                    "ffcsa_core/order_confirmation_email",
                    settings.DEFAULT_FROM_EMAIL,
                    user.email,
                    fail_silently=True,
                    context={
                        'first_name': user.first_name,
                        'home_delivery': user.profile.home_delivery,
                        'pickup_date': pickup,
                        'drop_site': 'Home Delivery' if user.profile.home_delivery else user.profile.drop_site,
                    }
                )

            cart.clear()
            cart.save()
