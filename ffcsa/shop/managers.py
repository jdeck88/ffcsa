from __future__ import unicode_literals

from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Manager, Q, Sum
from django.utils.timezone import now
from future.builtins import str, zip
from mezzanine.conf import settings
from mezzanine.core.managers import CurrentSiteManager

from ffcsa.core.availability import send_unavailable_email


class NotAllowedError(Exception):
    pass


class CartManager(Manager):

    def from_request(self, request):
        """
        Return a cart by ID stored in the session, updating its last_updated
        value and removing old carts. A new cart will be created (but not
        persisted in the database) if the session cart is expired or missing.
        """
        cart_id = request.session.get("cart", None)
        cart = self.current().filter(id=cart_id)
        last_updated = now()

        # Update timestamp and clear out old carts.
        if cart_id and cart.update(last_updated=last_updated):
            self.expired().delete()
        elif cart_id:
            # Cart has expired. Delete the cart id and
            # forget what checkout step we were up to.
            del request.session["cart"]
            cart_id = None
            try:
                del request.session["order"]["step"]
            except KeyError:
                pass

        # This is a cheeky way to save a database call: since Cart only has
        # two fields and we know both of their values, we can simply create
        # a cart instance without taking a trip to the database via the ORM.
        return self.model(id=cart_id, last_updated=last_updated)

    def expiry_time(self):
        """
        Datetime for expired carts.
        """
        return now() - timedelta(minutes=settings.SHOP_CART_EXPIRY_MINUTES)

    def current(self):
        """
        Unexpired carts.
        """
        return self.filter(last_updated__gte=self.expiry_time())

    def expired(self):
        """
        Expired carts.
        """
        return self.filter(last_updated__lt=self.expiry_time())


class CartItemManager(Manager):

    def handle_unavailable_variations(self, variations):
        """
        Remove any CartItems for the provided variations and inform the cart owners
        """
        for variation in variations:
            qs = self.filter(variation=variation)
            users = list(get_user_model().objects.filter(id__in=qs.values_list("cart__user_id")))
            qs.delete()

            if users:
                transaction.on_commit(lambda: send_unavailable_email(variation, bcc_addresses=[u.email for u in users]))

    def handle_changed_variation(self, variation):
        """
        Re-add the items to the cart for each variation.

        This will correctly update any vendor & quantities for existing CartItems
        This should be called whenever a ProductVariationVendor instance changes b/c
        the changes to quantity and/or vendor need to be reflected in the current CartItems
        """
        from ffcsa.shop.models import Cart
        from ffcsa.core.budgets import clear_cached_budget_for_user_id

        User = get_user_model()
        affected_users = {}

        stock = variation.number_in_stock

        cart_items = self.filter(variation=variation, cart__in=Cart.objects.current()).order_by('time')
        # we need to capture this here b/c once we delete the cart_items,
        # the quantity information is lost and will return 0
        ci = [{'quantity': i.quantity, 'cart': i.cart} for i in cart_items]

        # delete existing items and start adding one-by-one while we still have stock available
        # We do this b/c there is logic when adding an item to determine which vendor to purchase
        # that product from.
        cart_items.delete()

        for i in ci:
            cart = i['cart']
            user = cart.user_id

            if stock == 0:
                if user not in affected_users:
                    affected_users[user] = []
                affected_users[user].append((variation, None))
                continue

            qty = i['quantity']
            updated_quantity = min(qty, stock if stock is not None else qty)

            cart.add_item(variation, updated_quantity, False)

            if updated_quantity < qty:
                if user not in affected_users:
                    affected_users[user] = []
                    affected_users[user].append((variation, updated_quantity))

            if stock is not None:
                stock = stock - updated_quantity

        if affected_users:
            for user in User.objects.filter(id__in=affected_users.keys()):
                clear_cached_budget_for_user_id(user.id)

                for variation, quantity in affected_users[user.id]:
                    transaction.on_commit(
                        lambda: send_unavailable_email(variation, to_addr=user.email, quantity=quantity))


class OrderManager(CurrentSiteManager):

    def from_request(self, request):
        """
        Returns the last order made by session key. Used for
        Google Anayltics order tracking in the order complete view,
        and in tests.
        """
        orders = self.filter(key=request.session.session_key).order_by("-id")
        if orders:
            return orders[0]
        raise self.model.DoesNotExist

    def get_for_user(self, order_id, request):
        """
        Used for retrieving a single order, ensuring the user in
        the given request object can access it.
        """
        lookup = {"id": order_id}
        if not request.user.is_authenticated():
            lookup["key"] = request.session.session_key
        elif not request.user.is_staff:
            lookup["user_id"] = request.user.id
        return self.get(**lookup)

    def all_for_user(self, user):
        """
        Get all orders for the given user.

        Note: Only returns orders after 12-01-2017 as that is when we started calculating payments
        """
        return self \
            .filter(user_id=user.id) \
            .filter(time__gte=date(2017, 12, 1))  # started calculating payments 12/1/2017

    def total_for_user(self, user):
        total = self.all_for_user(user) \
            .aggregate(total=Sum('total'))['total']

        if total is None:
            total = Decimal(0)

        return total


def readOnly(*args, **kwargs):
    raise NotImplementedError("This is a read-only model")


class OrderItemManager(Manager):
    def create_from_cartitem(self, item):
        if item.variation.product.categories.count() > 1:
            category = ';'.join([str(c) for c in item.variation.product.categories.all()])
        else:
            category = item.category

        data = {
            'sku': item.sku,
            'description': item.description,
            'vendor_price': item.vendor_price,
            'unit_price': item.unit_price,
            'category': category,
            'in_inventory': item.in_inventory,
            'is_frozen': item.is_frozen
        }

        objs = []
        for v in item.vendors.all():
            d = data.copy()
            d.update({
                'vendor': v.vendor,
                'quantity': v.quantity
            })

            objs.append(self.create(**d))

        return objs

    def all_grouped(self):
        """
        Fetch all OrderItems for an order, grouping the results by sku
        """
        if not hasattr(self, 'instance'):
            raise NotAllowedError("all_grouped is only allowed when there is a parent instance for the OrderItem")

        qs = self.get_queryset().values('sku', 'unit_price', 'vendor_price', 'order_id', 'category', 'description',
                                        'in_inventory').annotate(quantity=Sum('quantity'),
                                                                 total_price=Sum('total_price'))
        result_list = []
        for row in qs:
            i = self.model(**row)
            i.save = readOnly
            i.delete = readOnly
            del i.id
            del i.vendor
            result_list.append(i)

        return result_list


class ProductOptionManager(Manager):

    def as_fields(self):
        """
        Return a dict of product options as their field names and
        choices.
        """
        options = defaultdict(list)
        for option in self.all():
            options["option%s" % option.type].append(option.name)
        return options


class ProductVariationManager(Manager):
    use_for_related_fields = True

    def create(self, *args, **kwargs):
        return super(ProductVariationManager, self).create(*args, **kwargs)

    def _empty_options_lookup(self, exclude=None):
        """
        Create a lookup dict of field__isnull for options fields.
        """
        if not exclude:
            exclude = {}
        return dict([("%s__isnull" % f.name, True)
                     for f in self.model.option_fields() if f.name not in exclude])

    def create_from_options(self, options):
        """
        Create all unique variations from the selected options.
        """
        if options:
            options = OrderedDict(options)
            # Build all combinations of options.
            variations = [[]]
            for values_list in list(options.values()):
                variations = [x + [y] for x in variations for y in values_list]
            for variation in variations:
                # Lookup unspecified options as null to ensure a
                # unique filter.
                variation = dict(list(zip(list(options.keys()), variation)))
                lookup = dict(variation)
                lookup.update(self._empty_options_lookup(exclude=variation))
                try:
                    self.get(**lookup)
                except self.model.DoesNotExist:
                    self.create(**variation)

    def ensure_default(self):
        """
        Ensure there is at least one default variation.
        """
        # total_variations = self.count()
        # if total_variations == 0:
        #     self.create()
        # elif total_variations > 1:
        #     self.filter(**self._empty_options_lookup()).delete()
        try:
            self.get(default=True)
        except self.model.DoesNotExist:
            first_variation = self.all()[0]
            first_variation.default = True
            first_variation.save()

    def set_default_images(self, deleted_image_ids):
        """
        Assign the first image for the product to each variation that
        doesn't have an image. Also remove any images that have been
        deleted via the admin to avoid invalid image selections.
        """
        variations = self.all()
        if not variations:
            return
        image = variations[0].product.images.exclude(id__in=deleted_image_ids)
        if image:
            image = image[0]
        for variation in variations:
            save = False
            if str(variation.image_id) in deleted_image_ids:
                variation.image = None
                save = True
            if image and not variation.image:
                variation.image = image
                save = True
            if save:
                variation.save()


class ProductActionManager(Manager):
    use_for_related_fields = True

    def _action_for_field(self, field):
        """
        Increases the given field by datetime.today().toordinal()
        which provides a time scaling value we can order by to
        determine popularity over time.
        """
        timestamp = datetime.today().toordinal()
        action, created = self.get_or_create(timestamp=timestamp)
        setattr(action, field, getattr(action, field) + 1)
        action.save()

    def added_to_cart(self):
        """
        Increase total_cart when product is added to cart.
        """
        self._action_for_field("total_cart")

    def purchased(self):
        """
        Increase total_purchased when product is purchased.
        """
        self._action_for_field("total_purchase")


class DiscountCodeManager(Manager):

    def active(self, *args, **kwargs):
        """
        Items flagged as active and in valid date range if date(s) are
        specified.
        """
        n = now()
        valid_from = Q(valid_from__isnull=True) | Q(valid_from__lte=n)
        valid_to = Q(valid_to__isnull=True) | Q(valid_to__gte=n)
        valid = self.filter(valid_from, valid_to, active=True)
        return valid.exclude(uses_remaining=0)

    def get_valid(self, code, cart):
        """
        Items flagged as active and within date range as well checking
        that the given cart contains items that the code is valid for.
        """
        total_price_valid = (Q(min_purchase__isnull=True) |
                             Q(min_purchase__lte=cart.item_total_price()))
        discount = self.active().get(total_price_valid, code=code)
        products = discount.all_products()
        if products.count() > 0:
            if products.filter(variations__sku__in=cart.skus()).count() == 0:
                raise self.model.DoesNotExist
        return discount


class PersistentCartManager(CartManager):
    def from_request(self, request):
        """
        Return a cart by user ID from the authenticated user, updating its last_updated
        value and removing old carts. A new cart will be created(but not
        persisted in the database) if the session cart is expired or missing.
        """

        user_id = request.user.id
        session_id = request.session.get(settings.SESSION_COOKIE_NAME, None)
        cart_query = None

        if user_id is not None:
            cart_query = self.current().filter(user_id=user_id)
        elif session_id is not None:
            cart_query = self.current().filter(session_id=session_id)
        else:
            # Anonymous user does not have a session; create a new one
            request.session.create()
            session_id = request.session.session_key
            request.session[settings.SESSION_COOKIE_NAME] = session_id

        cart_id = request.session.get("cart", None)
        cart = None if cart_query is None else cart_query.first()

        last_updated = now()
        # Update timestamp and clear out old carts and put the cart_id in the session
        # if cart and cart_query.update(last_updated=last_updated):
        if cart:
            self.expired().delete()
            cart_id = cart.id
            request.session["cart"] = cart_id
        elif cart_id:
            # Cart has expired. Delete the cart id and
            # forget what checkout step we were up to.
            del request.session["cart"]
            cart_id = None
            cart = None
            try:
                del request.session["order"]["step"]
            except KeyError:
                pass

        if cart:
            return cart
        else:
            return self.model(id=cart_id, last_updated=last_updated, user_id=user_id, session_id=session_id)
