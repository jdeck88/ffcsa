import csv
import tempfile
import zipfile
from collections import OrderedDict
from decimal import Decimal
from itertools import groupby

import labels
from django import forms
from django.contrib import admin, messages
from django.http import HttpResponse
from django.template.response import TemplateResponse
from mezzanine.conf import settings
from reportlab.graphics import shapes
from reportlab.pdfbase.pdfmetrics import stringWidth

from ffcsa.core.dropsites import get_color
from ffcsa.shop.invoice import generate_invoices
from ffcsa.shop.models import Category, Product, OrderItem

TWOPLACES = Decimal(10) ** -2


def export_as_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="ffcsa_order_export.csv"'

    writer = csv.writer(response)
    writer.writerow(
        ['Order Date', 'Last Name', 'Drop Site', 'Vendor', 'Category', 'Item', 'SKU', 'Member Price',
         'Vendor Price', 'Quantity', 'Member Total Price', 'Vendor Total Price', 'Parent Category Order On Invoice',
         'Child Category Order On Invoice', 'In Inventory', 'Allow Substitutions'])

    products = Product.objects.all()
    product_cache = {}
    for order in queryset:
        last_name = order.billing_detail_last_name
        drop_site = order.drop_site
        row_base = [order.time.date(), last_name, drop_site]

        for item in order.items.all():
            product = product_cache[item.sku] if item.sku in product_cache else products.filter(
                sku=item.sku).first()
            if not product:
                product = products.filter(title=item.description).first()
            if product:
                if not product.sku in product_cache:
                    product_cache[product.sku] = product
                if not item.vendor:
                    item.vendor = product.vendor
                if not item.category:
                    item.category = str(product.get_category())
                if not item.vendor_price:
                    item.vendor_price = product.vendor_price
            row = row_base.copy()
            vendor = item.vendor
            if not vendor and product:
                vendor = product.vendor
            row.append(vendor)
            row.append(item.category[0] if isinstance(
                item.category, (list, tuple)) else item.category)
            row.append(item.description)
            row.append(item.sku)
            row.append(item.unit_price.quantize(
                TWOPLACES) if item.unit_price else '')
            if item.vendor_price:
                row.append(item.vendor_price.quantize(TWOPLACES))
            else:
                row.append((item.unit_price * Decimal(.7)
                            ).quantize(TWOPLACES) if item.total_price else '')
            row.append(item.quantity)
            row.append(item.total_price.quantize(
                TWOPLACES) if item.total_price else '')
            if item.vendor_price:
                row.append(
                    (item.vendor_price * item.quantity).quantize(TWOPLACES))
            else:
                row.append((item.total_price * Decimal(.7)
                            ).quantize(TWOPLACES) if item.total_price else '')

            if product and product.order_on_invoice:
                parts = str(product.order_on_invoice).split('.')
                row.append(parts[0])
                row.append(parts[1] if len(parts) == 2 else '')
            else:
                category = product.get_category() if product else Category.objects.filter(
                    description__contains=item.category).first()
                if category:
                    add_blank = True
                    if category.parent:
                        row.append(category.parent.category.order_on_invoice)
                        add_blank = False

                    row.append(category.order_on_invoice)
                    if add_blank:
                        row.append('')

            row.append(item.in_inventory)
            row.append('yes' if order.allow_substitutions else 'no')
            writer.writerow(row)

    return response


export_as_csv.short_description = "Export As CSV"

FONT_NAME = "Helvetica"


def draw_label(label, width, height, order):
    last_name = order.billing_detail_last_name
    first_name = order.billing_detail_first_name
    drop_site = order.drop_site

    # Write the dropsite & color.
    font_size = 16
    name_width = stringWidth(drop_site, FONT_NAME, font_size)

    color, strokeColor = get_color(drop_site)
    # label.add(shapes.Circle(((height - 8) / 2) + 4, (height - 8) / 2, (height - 8) / 2, fillColor=color, strokeColor=strokeColor))
    rect_w = max(width / 2 + 4, name_width + 16)
    label.add(shapes.Rect(width - rect_w - 4, 4, rect_w, 32, rx=2,
                          ry=2, fillColor=color, strokeColor=strokeColor))

    label.add(shapes.String(width - 12, 12, drop_site,
                            fontSize=16, textAnchor='end', fontName=FONT_NAME))

    # Measure the width of the name and shrink the font size until it fits.
    font_size = 20
    text_width = width - 16
    name = "{}, {}".format(last_name, first_name)
    name_width = stringWidth(name, FONT_NAME, font_size)
    while name_width > text_width:
        font_size *= 0.8
        name_width = stringWidth(name, FONT_NAME, font_size)

    # Write out the name in the centre of the label with a random colour.
    # s = shapes.String(width / 2.0, height - 30, name, textAnchor="middle")
    s = shapes.String(8, height - 30, name)
    s.fontName = FONT_NAME
    s.fontSize = font_size
    label.add(s)


class SkipLabelsForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    select_across = forms.BooleanField(required=False, widget=forms.HiddenInput())
    skip = forms.IntegerField(max_value=30)


def order_sort(order):
    if order.drop_site in settings.DROP_SITE_ORDER:
        return (settings.DROP_SITE_ORDER.index(order.drop_site), order.billing_detail_last_name)
    return (len(settings.DROP_SITE_ORDER), order.billing_detail_last_name)


def create_labels(modeladmin, request, queryset):
    if 'cancel' in request.POST:
        messages.info(request, 'Canceled label creation.')
        return
    if 'create' in request.POST:
        form = SkipLabelsForm(request.POST)

        if form.is_valid():
            # Create an A4 portrait (210mm x 297mm) sheets with 2 columns and 8 rows of
            # labels. Each label is 90mm x 25mm with a 2mm rounded corner. The margins are
            # automatically calculated.
            # These settings are configured for Avery 5160 Address Labels
            specs = labels.Specification(217, 279, 3.25, 10, 70, 26.6, corner_radius=2, row_gap=0, column_gap=3,
                                         top_margin=8.25, left_margin=.8)

            sheet = labels.Sheet(specs, draw_label)

            to_skip = form.cleaned_data['skip']
            if to_skip > 0:
                used = []
                row = 1
                col = 1
                for i in range(1, to_skip + 1):
                    used.append((row, col))
                    # label sheet has 3 columns
                    if i % 3 == 0:
                        row += 1
                        col = 1
                    else:
                        col += 1

                sheet.partial_page(1, used)

            orders = [o for o in queryset]
            orders.sort(key=order_sort)
            for order in orders:
                if order.shipping_type is 'Home Delivery':
                    continue
                sheet.add_label(order)

            with tempfile.NamedTemporaryFile() as tmp:
                sheet.save(tmp)

                # Reset file pointer
                tmp.seek(0)

                # Write file data to response
                response = HttpResponse(
                    tmp.read(), content_type='application/pdf')
                response['Content-Disposition'] = 'attachment; filename="ffcsa_order_labels.pdf"'
                return response
    else:
        form = SkipLabelsForm(initial={
            'skip': 0,
            '_selected_action': request.POST.getlist(admin.ACTION_CHECKBOX_NAME),
            'select_across': request.POST.get('select_across', False)
        })

    return TemplateResponse(request, 'admin/skip_labels.html', {'form': form})


create_labels.short_description = "Create Box Labels"

DEFAULT_GROUP_KEY = 5


def keySort(categories):
    """ If updating, make sure to update product_keysort function in views.py"""
    def func(item):
        try:
            product = Product.objects.get(title=item.description, sku=item.sku)
            if product and product.order_on_invoice:
                return (product.order_on_invoice, item.description)
        except Product.DoesNotExist:
            pass

        try:
            cat = categories.get(titles=item.category)

            if not cat.parent:
                return (cat.order_on_invoice, item.description)

            if cat.parent and cat.parent.category:
                parent_order = cat.parent.category.order_on_invoice
                order = cat.order_on_invoice
                if order == 0:
                    order = DEFAULT_GROUP_KEY

                return (
                    float("{}.{}".format(parent_order, order)),
                    item.description
                )

        except Category.DoesNotExist:
            pass

        # just return a default number for category
        return (DEFAULT_GROUP_KEY, item.description)

    return func


def download_invoices(self, request, queryset):
    invoices = {}

    for invoice, order in generate_invoices(queryset):
        prefix = settings.DROP_SITE_ORDER.index(
            order.drop_site) if order.drop_site in settings.DROP_SITE_ORDER else len(settings.DROP_SITE_ORDER)
        invoices["{}_{}_{}_{}".format(
            prefix, order.drop_site, order.billing_detail_last_name, order.id)] = invoice

    with tempfile.SpooledTemporaryFile() as tmp:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as archive:
            for id, invoice in invoices.items():
                archive.writestr("order_{}.pdf".format(id), invoice.write_pdf())

        # Reset file pointer
        tmp.seek(0)

        # Write file data to response
        response = HttpResponse(
            tmp.read(), content_type='application/x-zip-compressed')
        response['Content-Disposition'] = 'attachment; filename="ffcsa_order_invoices.zip"'
        return response


download_invoices.short_description = "Download Invoices"


def get_non_substitutable_products(self, request, queryset):
    items = OrderItem.objects.filter(order__in=queryset) \
        .select_related('order') \
        .order_by('description')

    order_items = OrderedDict()
    for description, items in groupby(items, key=lambda x: x.description):
        items = list(items)
        order_items[description] = {
            'total': sum(i.quantity for i in items),
            'total_substitutable': sum(i.quantity for i in items if i.order.allow_substitutions)
        }

    return TemplateResponse(request, 'admin/non_substitutable_items.html', {'items': order_items})


get_non_substitutable_products.short_description = 'View Ordered Items Summary'
