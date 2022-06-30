from itertools import takewhile

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CharField
from django.db.models.base import ModelBase
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _
from django.utils.text import slugify
from future.builtins import super
from future.utils import with_metaclass
from mezzanine.conf import settings
from mezzanine.core.fields import FileField
from mezzanine.core.managers import DisplayableManager
from mezzanine.core.models import (ContentTyped, Displayable, Orderable,
                                   RichText)
from mezzanine.generic.fields import RatingField
from mezzanine.utils.models import AdminThumbMixin, upload_to

from ffcsa.shop import fields, managers
from ffcsa.shop.models.Priced import Priced


class BaseProduct(Displayable):
    """
    Exists solely to store ``DisplayableManager`` as the main manager.
    If it's defined on ``Product``, a concrete model, then each
    ``Product`` subclass loses the custom manager.
    """

    objects = DisplayableManager()

    class Meta:
        abstract = True


class ProductSeason(models.Model):
    # Seasons for products
    class Meta:
        verbose_name = 'Season'
        verbose_name_plural = 'Seasons'
    slug = models.SlugField(max_length=200, blank=True)
    name = models.SlugField(max_length=200)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        # create slug if not exists
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)


class Product(BaseProduct, Priced, RichText, ContentTyped, AdminThumbMixin):
    """
    Container model for a product that stores information common to
    all of its variations such as the product's title and description.
    """

    available = models.BooleanField(_("Available for purchase"),
                                    default=False)
    short_description = models.CharField(_("Short Description"), max_length=100,
                                   null=True, blank=True)
    image = CharField(_("Image"), max_length=100, blank=True, null=True)
    categories = models.ManyToManyField("Category", blank=True,
                                        verbose_name=_("Product categories"), related_name='category_products')
    date_added = models.DateTimeField(_("Date added"), auto_now_add=True,
                                      null=True)
    related_products = models.ManyToManyField("self",
                                              verbose_name=_("Related products"), blank=True)
    upsell_products = models.ManyToManyField("self",
                                             verbose_name=_("Upsell products"), blank=True)
    rating = RatingField(verbose_name=_("Rating"))
    seasons = models.ManyToManyField(ProductSeason, blank=True, null=True, related_name='seasons')

    unit = models.CharField(max_length=200, blank=True, null=True)
    weight = models.CharField(max_length=200, blank=True, null=True)

    order_on_invoice = models.FloatField(default=0, null=True, blank=True,
                                         help_text="Order this product will be printed on invoices. If set, this will override the product's category order_on_invoice setting. This is a float number for more fine grained control. (ex. '2.1' will be sorted the same as if the product's parent category order_on_invoice was 2 & the product's category order_on_invoice was 1).")
    is_dairy = models.BooleanField(default=False, verbose_name=_("Is Raw Dairy"),
                                   help_text="This is used to prevent unauthorized users from ordering raw dairy products")

    admin_thumb_field = "image"

    search_fields = {"variations__sku": 100}

    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")
        unique_together = ("sku", "site")

    @property
    def vendor(self):
        if self.variations.count() > 1:
            return None

        v = self.variations.first()

        if v.vendors.count() != 1:
            return None

        return v.vendors.first().title

    def has_stock(self):
        pass

    @property
    def descriptive_title(self):
        s = str(self.variations.first())
        return s

    def save(self, *args, **kwargs):
        self.set_content_model()
        super(Product, self).save(*args, **kwargs)

    @models.permalink
    def get_absolute_url(self):
        """
        If get_category returns a category, we will return a hierarchical path for the product under the category page,
        otherwise return a non-hierarchical url.
        """
        category = self.get_category()
        if category:
            return ("shop_category_product", (), {
                "category_slug": category.get_raw_slug(),
                "slug": self.slug})
        return ("shop_product", (), {"slug": self.slug})

    def copy_default_variation(self):
        """
        Copies the price and image fields from the default variation
        when the product is updated via the change view.
        """
        default = self.variations.get(default=True)
        default.copy_price_fields_to(self)
        # TODO I don't think we need this anymore
        # setattr(self, "weekly_inventory", getattr(default, "weekly_inventory"))
        # setattr(self, "in_inventory", getattr(default, "in_inventory"))
        setattr(self, "unit", getattr(default, "unit"))
        setattr(self, "weight", getattr(default, "weight"))
        if default.image:
            self.image = default.image.file.name
        self.save()

    def get_category(self):
        """
        Returns the single category this product is associated with, or None
        if the number of categories is not exactly 1.
        """
        categories = self.categories.all()
        if len(categories) == 1:
            return categories[0]
        return None


@python_2_unicode_compatible
class ProductImage(Orderable):
    """
    An image for a product - a relationship is also defined with the
    product's variations so that each variation can potentially have
    it own image, while the relationship between the ``Product`` and
    ``ProductImage`` models ensures there is a single set of images
    for the product.
    """

    file = FileField(_("Image"), max_length=255, format="Image",
                     upload_to=upload_to("shop.ProductImage.file", "product"))
    description = CharField(_("Description"), blank=True, max_length=100)
    product = models.ForeignKey("Product", related_name="images",
                                on_delete=models.CASCADE)

    class Meta:
        verbose_name = _("Image")
        verbose_name_plural = _("Images")
        order_with_respect_to = "product"

    def __str__(self):
        value = self.description
        if not value:
            value = self.file.name
        if not value:
            value = ""
        return value


class ProductOption(models.Model):
    """
    A selectable option for a product such as size or colour.
    """
    type = models.IntegerField(_("Type"),
                               choices=settings.SHOP_OPTION_TYPE_CHOICES)
    name = fields.OptionField(_("Name"))

    objects = managers.ProductOptionManager()

    def __str__(self):
        return "%s: %s" % (self.get_type_display(), self.name)

    class Meta:
        verbose_name = _("Product option")
        verbose_name_plural = _("Product options")


class ProductVariationUnit(models.Model):
    # Unit of Measurement (UOM) with for products its Code
    class Meta:
        verbose_name = 'Unit'
        verbose_name_plural = 'Units'

    name = models.SlugField(max_length=50)
    code = models.SlugField(max_length=50)

    def __str__(self) -> str:
        return self.code


class ProductVariationMetaclass(ModelBase):
    """
    Metaclass for the ``ProductVariation`` model that dynamcally
    assigns an ``fields.OptionField`` for each option in the
    ``SHOP_PRODUCT_OPTIONS`` setting.
    """

    def __new__(cls, name, bases, attrs):
        # Only assign new attrs if not a proxy model.
        if not ("Meta" in attrs and getattr(attrs["Meta"], "proxy", False)):
            for option in settings.SHOP_OPTION_TYPE_CHOICES:
                attrs["option%s" % option[0]] = fields.OptionField(option[1])
        args = (cls, name, bases, attrs)
        return super(ProductVariationMetaclass, cls).__new__(*args)


class ProductVariation(with_metaclass(ProductVariationMetaclass, Priced)):
    """
    A combination of selected options from
    ``SHOP_OPTION_TYPE_CHOICES`` for a ``Product`` instance.
    """
    # TODO do we need to extend Priced?

    product = models.ForeignKey("shop.Product", related_name="variations",
                                on_delete=models.CASCADE)
    _title = models.CharField(_("Title"), max_length=500, blank=True)
    short_description = models.CharField(_("Short Description"), max_length=100,
                                         null=True, blank=True)
    default = models.BooleanField(_("Default"), default=False)
    image = models.ForeignKey("ProductImage", verbose_name=_("Image"),
                              null=True, blank=True, on_delete=models.SET_NULL)
    num_in_stock = None
    is_frozen = models.BooleanField(default=False,
                                    help_text="Is this product frozen and should be packed with other frozen items into a cooler?")
    extra = models.IntegerField("% Extra", blank=True, null=True,
                                help_text="The % extra to order. This is used when a product is sold by the #, but it is difficult to weigh exactly to the # during pack out. The larger the item, the higher this % should be. The extra ordered will be rounded to the nearest whole number.")

    vendors = models.ManyToManyField('shop.Vendor', verbose_name="Vendors", related_name="variations",
                                     through='shop.VendorProductVariation')
    # on_delete=models.SET_NULL, blank=True,
    # null=True)

    unit = models.CharField(max_length=200, blank=True, null=True, help_text="Displays after the prices. Ex. $20 / {unit}")
    weight = models.CharField("Amount/Weight", max_length=200, blank=True, null=True, help_text="Displays on the bottom corner of the product image")
    objects = managers.ProductVariationManager()

    class Meta:
        ordering = ("-default",)
        # unique_together = ('product', '_title')

    def __str__(self):
        s = self.unit + ", " if self.unit else ""
        s += self.title
        if self.weight:
            s += f" {self.weight}"
        return s

    @property
    def title(self):
        return self._title if self._title else self.product.title

    @title.setter
    def title(self, value):
        self._title = value

    def clean(self):
        """
        Use the Product.title as title if title is not set
        """
        # if not self.title:
        #     self.title = self.product.title
        super(ProductVariation, self).clean()

    def save(self, *args, **kwargs):
        """
        Use the variation's ID as the SKU when the variation is first
        created.
        """
        super(ProductVariation, self).save(*args, **kwargs)
        if not self.sku:
            self.sku = self.id
            self.save()

    def get_absolute_url(self):
        return self.product.get_absolute_url()

    def validate_unique(self, *args, **kwargs):
        """
        Overridden to ensure SKU is unique per site, which can't be
        defined by ``Meta.unique_together`` since it can't span
        relationships.
        """
        super(ProductVariation, self).validate_unique(*args, **kwargs)
        if self.__class__.objects.exclude(id=self.id).filter(
                product__site_id=self.product.site_id, sku=self.sku).exists():
            raise ValidationError({"sku": _("SKU is not unique")})

    @classmethod
    def option_fields(cls):
        """
        Returns each of the model fields that are dynamically created
        from ``SHOP_OPTION_TYPE_CHOICES`` in
        ``ProductVariationMetaclass``.
        """
        all_fields = cls._meta.fields
        return [f for f in all_fields if isinstance(f, fields.OptionField) and
                not hasattr(f, "translated_field")]

    def options(self):
        """
        Returns the field values of each of the model fields that are
        dynamically created from ``SHOP_OPTION_TYPE_CHOICES`` in
        ``ProductVariationMetaclass``.
        """
        return [getattr(self, field.name) for field in self.option_fields()]

    @property
    def number_in_stock(self):
        stock = 0
        for vpv in self.vendorproductvariation_set.all():
            if vpv.num_in_stock is None:
                return None
            stock += vpv.num_in_stock
        return stock

    def live_num_in_stock(self):
        """
        Returns the live number in stock, which is
        ``self.num_in_stock - num in carts``. Also caches the value
        for subsequent lookups.
        """
        if not hasattr(self, "_cached_num_in_stock"):
            from ffcsa.shop.models import Cart, CartItem

            num_in_stock = self.number_in_stock
            if num_in_stock is not None:
                extra = round(self.number_in_stock * self.extra / 100) if self.extra else 0
                num_in_stock -= extra

                carts = Cart.objects.current()
                items = CartItem.objects.filter(variation=self, cart__in=carts)
                aggregate = items.aggregate(quantity_sum=models.Sum("vendors__quantity"))
                num_in_carts = aggregate["quantity_sum"]
                if num_in_carts is not None:
                    num_in_stock = num_in_stock - num_in_carts
            self._cached_num_in_stock = num_in_stock
        return self._cached_num_in_stock

    def has_stock(self, quantity=1):
        """
        Returns ``True`` if the given quantity is in stock, by checking
        against ``live_num_in_stock``. ``True`` is returned when
        ``num_in_stock`` is ``None`` which is how stock control is
        disabled.
        """
        live = self.live_num_in_stock()
        return live is None or quantity == 0 or live >= quantity

    def reduce_stock(self, quantity):
        """
        reduce the stock amount - called when an order is complete.
        """
        remaining = quantity
        for vpv in takewhile(lambda x: remaining > 0, self.vendorproductvariation_set.all()):
            if vpv.num_in_stock is None:
                return

            qty = min(remaining, vpv.num_in_stock)
            vpv.num_in_stock = vpv.num_in_stock - qty
            vpv.save()
            remaining = remaining - qty
