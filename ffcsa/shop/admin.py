from __future__ import unicode_literals

from copy import deepcopy

from django.contrib import admin
from django.db import transaction
from django.db.models import ImageField, Q
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _
from future.builtins import super, zip
from mezzanine.conf import settings
from mezzanine.core.admin import (BaseTranslationModelAdmin, ContentTypedAdmin,
                                  DisplayableAdmin, TabularDynamicInlineAdmin)
from mezzanine.pages.admin import PageAdmin
from mezzanine.utils.static import static_lazy as static
from nested_admin import nested

from ffcsa.core.budgets import clear_cached_budget_for_variation
from ffcsa.shop.actions import order_actions, product_actions
from ffcsa.shop.fields import MoneyField
from ffcsa.shop.forms import (OptionalContentAdminForm, DiscountAdminForm,
                              ImageWidget, MoneyWidget, OrderAdminForm,
                              ProductAdminForm, ProductChangelistForm,
                              ProductVariationAdminForm,
                              ProductVariationAdminFormset, VendorProductVariationAdminFormset)
from ffcsa.shop.models import (Category, DiscountCode, Order, OrderItem,
                               Product, ProductImage, ProductOption,
                               ProductVariation, Sale, Vendor, VendorProductVariation)
from ffcsa.shop.models.Cart import CartItem
from ffcsa.shop.models.Vendor import VendorCartItem
from ffcsa.shop.models.Product import  ProductVariationUnit
from ffcsa.shop.views import HAS_PDF

"""
Admin classes for all the shop models.

Many attributes in here are controlled by the ``SHOP_USE_VARIATIONS``
setting which defaults to True. In this case, variations are managed in
the product change view, and are created given the ``ProductOption``
values selected.

A handful of fields (mostly those defined on the abstract ``Priced``
model) are duplicated across both the ``Product`` and
``ProductVariation`` models, with the latter being the definitive
source, and the former supporting denormalised data that can be
referenced when iterating through products, without having to
query the underlying variations.

When ``SHOP_USE_VARIATIONS`` is set to False, a single variation is
still stored against each product, to keep consistent with the overall
model design. Since from a user perspective there are no variations,
the inlines for variations provide a single inline for managing the
one variation per product, so in the product change view, a single set
of price fields are available via the one variation inline.

Also when ``SHOP_USE_VARIATIONS`` is set to False, the denormalised
price fields on the product model are presented as editable fields in
the product change list - if these form fields are used, the values
are then pushed back onto the one variation for the product.
"""


def _flds(s): return [
    f.name for f in Order._meta.fields if f.name.startswith(s)]


billing_fields = _flds("billing_detail")
shipping_fields = _flds("shipping_detail")

################
#  CATEGORIES  #
################

# Categories fieldsets are extended from Page fieldsets, since
# categories are a Mezzanine Page type.
category_fieldsets = deepcopy(PageAdmin.fieldsets)
category_fieldsets[0][1]["fields"][3:3] = ["content", "products"]
category_fieldsets[0][1]["fields"].extend(['order_on_invoice'])
category_fieldsets += ((_("Product filters"), {
    "fields": ("sale", ("price_min", "price_max"), "combined"),
    "classes": ("collapse-closed",)},),)
if settings.SHOP_CATEGORY_USE_FEATURED_IMAGE:
    category_fieldsets[0][1]["fields"].insert(3, "featured_image")

# Options are only used when variations are in use, so only provide
# them as filters for dynamic categories when this is the case.
if settings.SHOP_USE_VARIATIONS:
    category_fieldsets[-1][1]["fields"] = (("options",) +
                                           category_fieldsets[-1][1]["fields"])


class CategoryAdmin(PageAdmin):
    form = OptionalContentAdminForm
    fieldsets = category_fieldsets
    formfield_overrides = {ImageField: {"widget": ImageWidget}}
    filter_horizontal = ("options", "products",)


################
#  VARIATIONS  #
################

class VendorProductVariationAdmin(nested.NestedTabularInline):
    verbose_name_plural = _("Variation Vendors")
    verbose_name = _("Vendor")
    model = ProductVariation.vendors.through
    min_num = 1
    extra = 0

    formset = VendorProductVariationAdminFormset


class ProductVariationAdmin(nested.NestedStackedInline):
    verbose_name_plural = _("Product Variations")
    inlines = (VendorProductVariationAdmin,)
    model = ProductVariation
    view_on_site = False
    fieldsets = (
        (None, {
            "fields": ["_title", "in_inventory", "weekly_inventory", "is_frozen", "extra",
                       ("vendor_price", "unit_price", "margin"),
                       ("unit", "weight", "sku"),
                       "default",
                       "image"],
        }),
    )
    min_num = 1
    extra = 0
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}
    form = ProductVariationAdminForm
    formset = ProductVariationAdminFormset
    ordering = ["option%s" % i for i in settings.SHOP_OPTION_ADMIN_ORDER]


class ProductImageAdmin(TabularDynamicInlineAdmin):
    model = ProductImage
    formfield_overrides = {ImageField: {"widget": ImageWidget}}


##############
#  PRODUCTS  #
##############


product_fieldsets = deepcopy(DisplayableAdmin.fieldsets)
product_fieldsets[0][1]["fields"].insert(2, "available")
product_fieldsets[0][1]["fields"].extend(
    ["content", "categories", "order_on_invoice", "is_dairy"])
product_fieldsets = list(product_fieldsets)

other_product_fields = []
if settings.SHOP_USE_RELATED_PRODUCTS:
    other_product_fields.append("related_products")
if settings.SHOP_USE_UPSELL_PRODUCTS:
    other_product_fields.append("upsell_products")
if len(other_product_fields) > 0:
    product_fieldsets.append((_("Other products"), {
        "classes": ("collapse-closed",),
        "fields": tuple(other_product_fields)}))

product_list_display = ["admin_thumb", "descriptive_title", "available",
                        "admin_link"]
product_list_editable = ["available"]

# If variations are used, set up the product option fields for managing
# variations. If not, expose the denormalised price fields for a product
# in the change list view.
extra_list_fields = ["vendor_price", "unit_price",
                     "in_inventory", "weekly_inventory", "num_in_stock", "order_on_invoice"]
product_list_display[3:3] = extra_list_fields
product_list_display[9:9] = ["vendor"]
product_list_editable.extend(extra_list_fields)


class CategoryListFilter(admin.SimpleListFilter):
    title = 'Category'

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'category'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        choices = [('-', '-')] + [
            (c.pk, force_text(c)) for c in Category.objects.published().order_by('title')
        ]

        return sorted(choices, key=lambda c: c[1])

    def queryset(self, request, queryset):
        # Return all product in the category or any child categories
        if self.value() == '-':
            return queryset.filter(category=None)
        if self.value():
            return queryset.filter(Q(category=self.value()) | Q(category__parent=self.value()))
        return queryset


class ProductAdmin(nested.NestedModelAdminMixin, ContentTypedAdmin, DisplayableAdmin):
    class Media:
        js = (static("shop/js/admin/product_variations.js"),
              static('shop/js/admin/product_margins.js'))
        css = {"all": (static("shop/css/admin/product.css"),)}

    actions = [product_actions.export_price_list]

    list_display = product_list_display
    list_display_links = ("admin_thumb", "descriptive_title")
    list_editable = product_list_editable
    list_filter = ("status", "available", CategoryListFilter, "variations__vendors")
    filter_horizontal = ("categories",) + tuple(other_product_fields)
    search_fields = ("title", "content", "categories__title", "variations__sku")
    inlines = (ProductImageAdmin, ProductVariationAdmin)
    form = ProductAdminForm
    fieldsets = product_fieldsets
    ordering = ('-available',)

    def get_queryset(self, request):
        # we prefetch variations__vendorproductvariation_set b/c it contains the num_in_stock attribute
        return super(ProductAdmin, self) \
            .get_queryset(request) \
            .prefetch_related('variations__vendorproductvariation_set') \
            .prefetch_related('variations__vendors') \
            .prefetch_related('categories__parent__category')

    def save_form(self, request, form, change):
        if isinstance(form, ProductChangelistForm):
            return form.save(request, commit=False)
        return form.save(commit=False)

    def save_model(self, request, obj, form, change):
        """
        Store the product ID for creating variations in save_formset.

        Inform customers when a product in their cart has become unavailable
        """
        updating = obj.id is not None
        super(ProductAdmin, self).save_model(request, obj, form, change)
        # We store the product ID so we can retrieve a clean copy of
        # the product in save_formset, see: GH #301.
        self._product_id = obj.id

        if updating and form.has_changed():
            if 'available' in form.changed_data and not obj.available:
                CartItem.objects.handle_unavailable_variations(obj.variations.all())

    def save_formset(self, request, form, formset, change):
        """

        Here be dragons. We want to perform these steps sequentially:

        - Save variations formset
        - Run the required variation manager methods:
          (create_from_options, manage_empty, etc)
        - Save the images formset

        The variations formset needs to be saved first for the manager
        methods to have access to the correct variations. The images
        formset needs to be run last, because if images are deleted
        that are selected for variations, the variations formset will
        raise errors when saving due to invalid image selections. This
        gets addressed in the set_default_images method.

        An additional problem is the actual ordering of the inlines,
        which are in the reverse order for achieving the above. To
        address this, we store the images formset as an attribute, and
        then call save on it after the other required steps have
        occurred.

        """

        product = self.model.objects.get(id=self._product_id)

        # Store the images formset for later saving, otherwise save the
        # formset.
        if formset.model == ProductImage:
            self._images_formset = formset
        else:
            super(ProductAdmin, self).save_formset(request, form, formset,
                                                   change)

        if formset.model == VendorProductVariation:
            if formset.has_changed():
                CartItem.objects.handle_changed_variation(formset.instance)

        # Run each of the variation manager methods if we're saving
        # the variations formset.
        if formset.model == ProductVariation:

            # Build up selected options for new variations.
            # options = dict([(f, request.POST.getlist(f)) for f in option_fields
            #                 if request.POST.getlist(f)])
            # Create a list of image IDs that have been marked to delete.
            deleted_images = [request.POST.get(f.replace("-DELETE", "-id"))
                              for f in request.POST
                              if f.startswith("images-") and f.endswith("-DELETE")]

            CartItem.objects.handle_unavailable_variations([form.instance for form in formset.deleted_forms])

            for form in formset.forms:
                # if missing initial data, this is a new ProductVariation   only need to call this if unit_price is changed
                if 'unit_price' in form.changed_data and form.initial:
                    clear_cached_budget_for_variation(form.instance)

            # Create new variations for selected options.
            # product.variations.create_from_options(options)
            # Ensure there is a default variation
            product.variations.ensure_default()

            # Remove any images deleted just now from variations they're
            # assigned to, and set an image for any variations without one.
            product.variations.set_default_images(deleted_images)

            # Save the images formset stored previously.
            super(ProductAdmin, self).save_formset(request, form,
                                                   self._images_formset, change)

            # Run again to allow for no images existing previously, with
            # new images added which can be used as defaults for variations.
            product.variations.set_default_images(deleted_images)

            # Copy duplicate fields (``Priced`` fields) from the default
            # variation to the product.
            product.copy_default_variation()

            # Save every translated fields from ``ProductOption`` into
            # the required ``ProductVariation``
            if settings.USE_MODELTRANSLATION:
                from collections import OrderedDict
                from modeltranslation.utils import (build_localized_fieldname
                                                    as _loc)
                for opt_name in options:
                    for opt_value in options[opt_name]:
                        opt_obj = ProductOption.objects.get(type=opt_name[6:],
                                                            name=opt_value)
                        params = {opt_name: opt_value}
                        for var in product.variations.filter(**params):
                            for code in OrderedDict(settings.LANGUAGES):
                                setattr(var, _loc(opt_name, code),
                                        getattr(opt_obj, _loc('name', code)))
                            var.save()

    @transaction.atomic()
    def changelist_view(self, request, extra_context=None):
        return super(ProductAdmin, self).changelist_view(request, extra_context=None)

    def get_changelist_form(self, request, **kwargs):
        # we set the choices here b/c the default Django Formset will cause ModelChoiceField to query the db for
        # each form rendered. By setting the choices here, we only issue a single db query
        vendor_choices = [(v.pk, v) for v in
                          Vendor.objects.all().order_by('title')]
        vendor_choices.insert(0, ('', '-- Select a Vendor --'))  # provide empty option
        ProductChangelistForm.base_fields['vendor'].choices = vendor_choices
        return ProductChangelistForm

    # def get_formsets_with_inlines(self, request, obj=None):
    #     return super(ProductAdmin, self).get_formsets_with_inlines(request, obj=obj)

    def cat(self, obj):
        return 'Multiple' if obj.categories.count() > 1 else obj.get_category()

    cat.short_description = 'Category'


class ProductOptionAdmin(BaseTranslationModelAdmin):
    ordering = ("type", "name")
    list_display = ("type", "name")
    list_display_links = ("type",)
    list_editable = ("name",)
    list_filter = ("type",)
    search_fields = ("type", "name")
    radio_fields = {"type": admin.HORIZONTAL}


class OrderItemInline(admin.TabularInline):
    verbose_name_plural = _("Items")
    model = OrderItem
    extra = 0
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}
    fields = ('category', 'vendor', 'vendor_price', 'sku',
              'description', 'quantity', 'unit_price', 'total_price')


def address_pairs(fields):
    """
    Zips address fields into pairs, appending the last field if the
    total is an odd number.
    """
    pairs = list(zip(fields[::2], fields[1::2]))
    if len(fields) % 2:
        pairs.append(fields[-1])
    return pairs


order_list_display = ("id", "billing_name", "total", "time", "status",
                      "transaction_id")
if HAS_PDF:
    order_list_display += ("invoice",)


# order_admin_fieldsets_fields_list = list(order_admin_fieldsets[2][1]["fields"])
# order_admin_fieldsets_fields_list.insert(1, 'attending_dinner')
# order_admin_fieldsets_fields_list.insert(2, 'drop_site')
# order_admin_fieldsets[2][1]["fields"] = tuple(
#     order_admin_fieldsets_fields_list)


class OrderAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": (static("shop/css/admin/order.css"),)}

    actions = [order_actions.export_as_csv, order_actions.download_invoices, order_actions.create_labels,
               order_actions.get_non_substitutable_products]
    ordering = ("status", "-id")
    list_display = order_list_display
    list_editable = ("status",)
    list_filter = ("status", "time", "drop_site")
    list_display_links = ("id", "billing_name",)
    search_fields = (["id", "status", "transaction_id"] +
                     billing_fields + shipping_fields)
    date_hierarchy = "time"
    radio_fields = {"status": admin.HORIZONTAL}
    inlines = (OrderItemInline,)
    form = OrderAdminForm
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}
    fieldsets = (
        (_("Billing details"), {"fields": [
                                              'order_date', 'user'] + address_pairs(billing_fields)}),
        (_("Shipping details"), {"fields": address_pairs(shipping_fields)}),
        (None, {"fields": ("additional_instructions", 'attending_dinner', 'drop_site', ("shipping_total",
                                                                                        "shipping_type"),
                           ('tax_total', 'tax_type'),
                           ("discount_total", "discount_code"), "item_total",
                           ("total", "status"), "transaction_id")}),
    )

    def change_view(self, *args, **kwargs):
        if kwargs.get("extra_context", None) is None:
            kwargs["extra_context"] = {}
        kwargs["extra_context"]["has_pdf"] = HAS_PDF
        return super(OrderAdmin, self).change_view(*args, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        form = super(OrderAdmin, self).get_form(request, obj, **kwargs)

        for name, field in form.base_fields.items():
            field.required = False

            if name == 'user':
                field.disabled = bool(obj)
                field.initial = obj.user_id if obj else None
            if name == 'order_date':
                field.disabled = bool(obj)
                if obj:
                    field.initial = obj.time.date()

        return form

    def save_formset(self, request, form, formset, change):
        total = 0
        for item in formset.cleaned_data:
            if not item['DELETE']:
                item['total_price'] = item['unit_price'] * item['quantity']
                total += item['total_price']

        order = form.instance
        order.item_total = total

        if order.discount_code:
            try:
                dc = DiscountCode.objects.get(code=order.discount_code)
                order.discount_total = dc.calculate(total)
                order.total = total - order.discount_total
            except DiscountCode.DoesNotExist:
                order.total = total - order.discount_total
        else:
            order.total = total

        formset.save()
        order.save()


class SaleAdmin(admin.ModelAdmin):
    list_display = ("title", "active", "discount_deduct", "discount_percent",
                    "discount_exact", "valid_from", "valid_to")
    list_editable = ("active", "discount_deduct", "discount_percent",
                     "discount_exact", "valid_from", "valid_to")
    filter_horizontal = ("categories", "products")
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}
    form = DiscountAdminForm
    fieldsets = (
        (None, {"fields": ("title", "active")}),
        (_("Apply to product and/or products in categories"),
         {"fields": ("products", "categories")}),
        (_("Reduce unit price by"),
         {"fields": (("discount_deduct", "discount_percent",
                      "discount_exact"),)}),
        (_("Sale period"), {"fields": (("valid_from", "valid_to"),)}),
    )


class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ("title", "active", "code", "discount_deduct",
                    "discount_percent", "min_purchase", "free_shipping", "valid_from",
                    "valid_to")
    list_editable = ("active", "code", "discount_deduct", "discount_percent",
                     "min_purchase", "free_shipping", "valid_from", "valid_to")
    filter_horizontal = ("categories", "products")
    formfield_overrides = {MoneyField: {"widget": MoneyWidget}}
    form = DiscountAdminForm
    fieldsets = (
        (None, {"fields": ("title", "active", "code")}),
        (_("Apply to product and/or products in categories"),
         {"fields": ("products", "categories")}),
        (_("Reduce unit price by"),
         {"fields": (("discount_deduct", "discount_percent"),)}),
        (None, {"fields": (("min_purchase", "free_shipping"),)}),
        (_("Valid for"),
         {"fields": (("valid_from", "valid_to", "uses_remaining"),)}),
    )


vendor_fieldsets = deepcopy(DisplayableAdmin.fieldsets)
vendor_fieldsets[0][1]["fields"][2] = ('publish_date',)
vendor_fieldsets[0][1]["fields"].extend(['featured_image', 'content', 'email', 'auto_send_order'])


class VendorAdmin(DisplayableAdmin):
    fieldsets = vendor_fieldsets
    list_display = ("title", "email", "auto_send_order", "admin_link")
    list_editable = ("email", "auto_send_order")
    form = OptionalContentAdminForm


admin.site.register(Category, CategoryAdmin)
admin.site.register(Product, ProductAdmin)
# if settings.SHOP_USE_VARIATIONS:
#     admin.site.register(ProductOption, ProductOptionAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(Sale, SaleAdmin)
admin.site.register(DiscountCode, DiscountCodeAdmin)
admin.site.register(Vendor, VendorAdmin)
