from decimal import Decimal

from django.db import models
from django.db.models import CharField
from django.urls import reverse
from django.utils.translation import pgettext_lazy as __, ugettext
from django.utils.translation import ugettext as _
from mezzanine.conf import settings
from mezzanine.core.models import SiteRelated

from ffcsa.shop import fields, managers
from ffcsa.shop.models.Product import ProductVariation
from ffcsa.shop.models.DiscountCode import DiscountCode
from ffcsa.shop.utils import clear_session


class Order(SiteRelated):
    billing_detail_first_name = CharField(_("First name"), max_length=100)
    billing_detail_last_name = CharField(_("Last name"), max_length=100)
    billing_detail_street = CharField(_("Street"), max_length=100)
    billing_detail_city = CharField(_("City/Suburb"), max_length=100)
    billing_detail_state = CharField(_("State/Region"), max_length=100)
    billing_detail_postcode = CharField(_("Zip/Postcode"), max_length=10)
    billing_detail_country = CharField(_("Country"), max_length=100)
    billing_detail_phone = CharField(_("Phone"), max_length=20)
    billing_detail_phone_2 = CharField(
        _("Alt. Phone"), blank=True, max_length=20)
    billing_detail_email = models.EmailField(_("Email"), max_length=254)
    shipping_detail_first_name = CharField(_("First name"), max_length=100)
    shipping_detail_last_name = CharField(_("Last name"), max_length=100)
    shipping_detail_street = CharField(_("Street"), max_length=100)
    shipping_detail_city = CharField(_("City/Suburb"), max_length=100)
    shipping_detail_state = CharField(_("State/Region"), max_length=100)
    shipping_detail_postcode = CharField(_("Zip/Postcode"), max_length=10)
    shipping_detail_country = CharField(_("Country"), max_length=100)
    shipping_detail_phone = CharField(_("Phone"), max_length=20)
    shipping_instructions = models.TextField(_("Shipping instructions"), blank=True)
    additional_instructions = models.TextField(_("Additional instructions"),
                                               blank=True)
    time = models.DateTimeField(_("Time"), auto_now_add=True, null=True)
    key = CharField(max_length=40, db_index=True)
    user_id = models.IntegerField(blank=True, null=True)
    shipping_type = CharField(_("Shipping type"), max_length=50, blank=True)
    shipping_total = fields.MoneyField(_("Shipping total"))
    tax_type = CharField(_("Tax type"), max_length=50, blank=True)
    tax_total = fields.MoneyField(_("Tax total"))
    item_total = fields.MoneyField(_("Item total"))
    discount_code = fields.DiscountCodeField(_("Discount code"), blank=True)
    discount_total = fields.MoneyField(_("Discount total"))
    total = fields.MoneyField(_("Order total"))
    transaction_id = CharField(_("Transaction ID"), max_length=255, null=True,
                               blank=True)

    status = models.IntegerField(_("Status"),
                                 choices=settings.SHOP_ORDER_STATUS_CHOICES,
                                 default=settings.SHOP_ORDER_STATUS_CHOICES[0][0])

    attending_dinner = models.IntegerField(blank=False, null=False, default=0)
    drop_site = models.CharField(blank=True, max_length=255)

    # TODO just fetch these prefrence from the user?
    plastic_bags = models.BooleanField(_("Use Plastic Bags"), default=False)
    allow_substitutions = models.BooleanField(
        _("Allow product substitutions"), default=False)

    objects = managers.OrderManager()

    # These are fields that are stored in the session. They're copied to
    # the order in setup() and removed from the session in complete().
    session_fields = ("shipping_type", "shipping_total", "discount_total",
                      "discount_code", "tax_type", "tax_total")

    class Meta:
        verbose_name = __("commercial meaning", "Order")
        verbose_name_plural = __("commercial meaning", "Orders")
        ordering = ("-id",)

    def __str__(self):
        return "#%s %s %s" % (self.id, self.billing_name(), self.time)

    def billing_name(self):
        return "%s %s" % (self.billing_detail_first_name,
                          self.billing_detail_last_name)

    def setup(self, request):
        """
        Set order fields that are stored in the session, item_total
        and total based on the given cart, and copy the cart items
        to the order. Called in the final step of the checkout process
        prior to the payment handler being called.
        """
        self.key = request.session.session_key
        self.user_id = request.user.id
        for field in self.session_fields:
            if field in request.session:
                setattr(self, field, request.session[field])
        self.total = self.item_total = request.cart.item_total_price()
        if self.shipping_total is not None:
            self.shipping_total = Decimal(str(self.shipping_total))
            self.total += self.shipping_total
        if self.discount_total is not None:
            self.total -= Decimal(self.discount_total)
        if self.tax_total is not None:
            self.total += Decimal(self.tax_total)
        self.save()  # We need an ID before we can add related items.
        for item in request.cart:
            self.items.create_from_cartitem(item)

    def complete(self, request):
        """
        Remove order fields that are stored in the session, reduce the
        stock level for the items in the order, decrement the uses
        remaining count for discount code (if applicable) and then
        delete the cart.
        """
        self.save()  # Save the transaction ID.
        discount_code = request.session.get('discount_code')
        clear_session(request, "order", *self.session_fields)
        for item in request.cart:
            try:
                variation = ProductVariation.objects.get(sku=item.sku)
            except ProductVariation.DoesNotExist:
                pass
            else:
                variation.reduce_stock(item.quantity)
                variation.product.actions.purchased()
        if discount_code:
            DiscountCode.objects.active().filter(code=discount_code).update(
                uses_remaining=models.F('uses_remaining') - 1)
        request.cart.delete()
        del request.session['cart']

    def details_as_dict(self):
        """
        Returns the billing_detail_* and shipping_detail_* fields
        as two name/value pairs of fields in a dict for each type.
        Used in template contexts for rendering each type as groups
        of names/values.
        """
        context = {}
        for fieldset in ("billing_detail", "shipping_detail"):
            fields = [(f.verbose_name, getattr(self, f.name)) for f in
                      self._meta.fields if f.name.startswith(fieldset)]
            context["order_%s_fields" % fieldset] = fields
        return context

    def invoice(self):
        """
        Returns the HTML for a link to the PDF invoice for use in the
        order listing view of the admin.
        """
        url = reverse("shop_invoice", args=(self.id,))
        text = ugettext("Download PDF invoice")
        return "<a href='%s?format=pdf'>%s</a>" % (url, text)

    invoice.allow_tags = True
    invoice.short_description = ""


class OrderItem(models.Model):
    """
    A selected product in a completed order.
    """
    sku = fields.SKUField()
    order = models.ForeignKey("Order", related_name="items", on_delete=models.CASCADE)

    description = CharField(_("Description"), max_length=2000)

    quantity = models.IntegerField(_("Quantity"), default=0)
    unit_price = fields.MoneyField(_("Unit price"), default=Decimal("0"))
    vendor_price = fields.MoneyField(_("Vendor price"), blank=True, null=True)
    total_price = fields.MoneyField(_("Total price"), default=Decimal("0"))

    category = models.TextField(blank=True)
    vendor = models.CharField(blank=True, max_length=255)
    in_inventory = models.BooleanField(_("FFCSA Inventory"), default=False, blank=False, null=False)
    is_frozen = models.BooleanField(default=False)

    objects = managers.OrderItemManager()

    class Meta:
        base_manager_name = 'objects'

    def __str__(self):
        return self.description
        # return ""

    def save(self, *args, **kwargs):
        """
        Set the total price based on the given quantity. If the
        quantity is zero, which may occur via the cart page, just
        delete it.
        """
        if not self.id or self.quantity > 0:
            self.total_price = self.unit_price * self.quantity
            super(OrderItem, self).save(*args, **kwargs)
        else:
            self.delete()
