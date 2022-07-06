from datetime import timedelta
from functools import reduce
from operator import iand, ior
from collections import defaultdict

from django.db import models
from django.db.models import Q
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _
from mezzanine.core.fields import FileField
from mezzanine.core.models import RichText
from mezzanine.pages.models import Page
from mezzanine.utils.models import upload_to

from ffcsa.shop import fields
from ffcsa.shop.models.Product import Product, ProductVariation


class Category(Page, RichText):
    """
    A category of products on the website.
    """

    featured_image = FileField(verbose_name=_("Featured Image"),
                               upload_to=upload_to(
                                   "shop.Category.featured_image", "shop"),
                               format="Image", max_length=255, null=True, blank=True)
    products = models.ManyToManyField("shop.Product", blank=True,
                                      verbose_name=_("Products"),
                                      through=Product.categories.through)
    options = models.ManyToManyField("shop.ProductOption", blank=True,
                                     verbose_name=_("Product options"),
                                     related_name="product_options")
    sale = models.ForeignKey("shop.Sale", verbose_name=_("Sale"),
                             blank=True, null=True, on_delete=models.CASCADE)
    price_min = fields.MoneyField(_("Minimum price"), blank=True, null=True)
    price_max = fields.MoneyField(_("Maximum price"), blank=True, null=True)
    combined = models.BooleanField(_("Combined"), default=True,
                                   help_text=_("If checked, "
                                               "products must match all specified filters, otherwise products "
                                               "can match any specified filter."))
    order_on_invoice = models.IntegerField(default=0,
                                           help_text="Order this category will be printed on invoices.")

    class Meta:
        verbose_name = _("Product category")
        verbose_name_plural = _("Product categories")

    def filters(self):
        """
        Returns product filters as a Q object for the category.
        """
        # Build a list of Q objects to filter variations by.
        filters = []
        # Build a lookup dict of selected options for variations.
        options = self.options.as_fields()
        if options:
            lookup = dict([("%s__in" % k, v) for k, v in options.items()])
            filters.append(Q(**lookup))
        # Q objects used against variations to ensure sale date is
        # valid when filtering by sale, or sale price.
        n = now()
        valid_sale_from = Q(sale_from__isnull=True) | Q(sale_from__lte=n)
        valid_sale_to = Q(sale_to__isnull=True) | Q(sale_to__gte=n)
        valid_sale_date = valid_sale_from & valid_sale_to
        # Filter by variations with the selected sale if the sale date
        # is valid.
        if self.sale_id:
            filters.append(Q(sale_id=self.sale_id) & valid_sale_date)
        # If a price range is specified, use either the unit price or
        # a sale price if the sale date is valid.
        if self.price_min or self.price_max:
            prices = []
            if self.price_min:
                sale = Q(sale_price__gte=self.price_min) & valid_sale_date
                prices.append(Q(unit_price__gte=self.price_min) | sale)
            if self.price_max:
                sale = Q(sale_price__lte=self.price_max) & valid_sale_date
                prices.append(Q(unit_price__lte=self.price_max) | sale)
            filters.append(reduce(iand, prices))
        # Turn the variation filters into a product filter.
        operator = iand if self.combined else ior
        products = Q(id__in=self.products.only("id"))
        if filters:
            filters = reduce(operator, filters)
            variations = ProductVariation.objects.filter(filters)
            filters = [Q(variations__in=variations)]
            # If filters exist, checking that products have been
            # selected is neccessary as combining the variations
            # with an empty ID list lookup and ``AND`` will always
            # result in an empty result.
            if self.products.count() > 0:
                filters.append(products)
            return reduce(operator, filters)
        return products

    def get_raw_slug(self):
        """
        Returns this object's slug stripped of its parent's slug.
        """

        def get_non_category_slug(parent):
            if not parent or not parent.slug:
                return None

            if not parent.category:
                return parent.slug

            return get_non_category_slug(parent.parent)

        root = get_non_category_slug(self.parent)
        if not root:
            return self.slug
        return self.slug.lstrip(root).lstrip('/')

    @classmethod
    def shop_menu_categories(self, is_authenticated=False):
        """
        List of categories and it's published sub categories for products to be filtered
        """
        categories = []
        qs = Category.objects.filter(parent__isnull=True)
        if not is_authenticated:
            qs = qs.filter(login_required=False)
        for cat in qs.order_by('_order'):
            if not cat.published():
                continue
            # sub_cat( published and have at least one available product)
            sub_cats = [c.title for c in cat.children.all().order_by('_order') if
                        c.published() and (is_authenticated or c.login_required is False) and Product.objects.filter(
                            categories__id=c.id, available=True).count() > 0]

            # no products in the category and no children w/ products, skip it
            if len(sub_cats) is 0 and Product.objects.filter(categories__id=cat.id, available=True).count() is 0:
                continue

            categories.append({
                'title': cat.title,
                'display_name': cat.title.upper(),
                'sub_cats': sub_cats
            })
        return categories
