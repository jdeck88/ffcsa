import logging
from collections import namedtuple, OrderedDict
from itertools import groupby

from ffcsa.shop.fields import MoneyField
from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Sum, Q, Case, When, IntegerField, Value, Subquery, OuterRef, F, ExpressionWrapper
from django.template.loader import select_template, get_template
from weasyprint import HTML

from ffcsa.shop.models import OrderItem, Vendor, Product, Order
from ffcsa.core.views import product_keySort

logger = logging.getLogger(__name__)


def generate_weekly_order_reports(date):
    qs = OrderItem.objects \
        .filter(order__time__date=date) \
        .values('description', 'category', 'vendor', 'vendor_price', 'in_inventory') \
        .annotate(total_price=Sum(ExpressionWrapper(F('vendor_price') * F('quantity'), output_field=MoneyField()))) \
        .annotate(quantity=Sum('quantity'))

    # zip_files = []
    docs = []

    # generate orders & pickup sheets
    vendor_orders = list(get_vendor_orders(date, qs))

    for vo in vendor_orders:
        # send_order_to_vendor(order.write_pdf(), vendor, vendor_title, date)
        if vo.vendor_title.lower() != 'deck family farm':
            docs.append(vo.pickuplist)
        # zip_files.append(("{}_pickup_list_{}.pdf".format(vendor_title, date), pickuplist))
        # we need 2 of these
        # if vo.vendor_title.lower() == 'deck family farm':
            # for some reason this doesn't render the title???
            # docs.append(vo.pickuplist.copy())
            # zip_files.append(("{}_pickup_list_karina_{}.pdf".format(vendor_title, date), pickuplist))

    # generate packing lists

    # Woven Roots pack sheet
    # zip_files.append(("woven_roots_dairy_packlist_{}.pdf".format(date), generate_woven_roots_dairy_packlist(date)))
    docs.append(generate_woven_roots_dairy_packlist(date))

    # frozen items bulk list
    # zip_files.append(("frozen_bulk_{}_packlist.pdf".format(date), generate_frozen_items_report(date, qs)))
    # docs.append(generate_frozen_items_report(date, qs))

    # FFCSA Inventory Products
    # zip_files.append(("ffcsa_inventory_{}.pdf".format(date), generate_ffcsa_inventory_packlist(date, qs)))
    docs.append(generate_ffcsa_inventory_packlist(date, qs))

    # DFF Dairy totals sheet
    # zip_files.append(("dff_dairy_packlist_{}.pdf".format(date), generate_dff_dairy_packlist(date)))
    docs.append(generate_dff_dairy_packlist(date))

    # Dairy pack sheet
    # zip_files.append(("dairy_packlist_{}.pdf".format(date), generate_dairy_packlist(date)))
    docs.append(generate_dairy_packlist(date))

    # Frozen items pack sheet
    # docs.append(generate_frozen_items_packlist(date, qs))
    docs.extend(generate_frozen_items_packlist(date, qs))

    # Grain & Bean Sheet
    # zip_files.append(("grain_and_bean_packlist_{}.pdf".format(date), generate_grain_and_bean_packlist(date)))
    # docs.append(generate_grain_and_bean_packlist(date, qs))

    # Market Checklists
    checklist = generate_market_checklists(date)
    # zip_files.append(("market_checklists_{}.pdf".format(date), checklist))
    if checklist:
        docs.append(checklist)

    # checklist = generate_home_delivery_checklists(date)
    # if checklist:
    #     docs.append(checklist)

    # notes = generate_home_delivery_notes(date)
    # if notes:
    #     docs.append(notes)

    checklist = generate_master_checklist(date)
    if checklist:
        docs.append(checklist)

    # Packing Order Sheet
    # zip_files.append(("product_order_{}.pdf".format(date), generate_product_order(date)))
    docs.append(generate_product_order(date))

    doc = docs[0]
    doc = doc.copy([p for d in docs for p in d.pages])  # uses the metadata from doc

    return vendor_orders, doc

    # for file, contents in zip_files:
    #     with tempfile.NamedTemporaryFile(
    #             delete=False, dir="app-messages", suffix='.' + file.split('.')[1],
    #             prefix=file + "_%s" % datetime.datetime.now().timestamp()) as t:
    #         t.write(contents)

    # with tempfile.SpooledTemporaryFile() as tmp:
    # with tempfile.NamedTemporaryFile(
    #         delete=False, dir="app-messages", suffix='.zip') as tmp:
    #     with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as archive:
    #         for fname, contents in zip_files:
    #             archive.writestr(fname, contents)


VendorOrder = namedtuple('VendorOrder', ['order', 'pickuplist', 'vendor_title', 'vendor'])


def get_vendor_orders(date, qs):
    vendors = Vendor.objects.all()
    vendor_items = {}

    for item in qs.filter(in_inventory=False):
        items = vendor_items.setdefault(item['vendor'], [])
        items.append(item)

    for vendor_title, items in vendor_items.items():
        if vendor_title.lower() == 'deck family farm':
            # we sort so we can use the django regroup filter
            items.sort(key=lambda x: (x['category'], x['description']))
        else:
            items.sort(key=lambda x: x['description'])
        context = {
            "items": items,
            "vendor": vendor_title,
            "date": date,
            "grand_total": sum([i['total_price'] for i in items])
        }

        vendor = None
        try:
            vendor = vendors.get(title=vendor_title)
        except Vendor.DoesNotExist:
            pass

        # send order to vendor

        html = select_template([
            "shop/reports/{}_vendor_order_pdf.html".format(vendor_title.lower()),
            "shop/reports/vendor_order_pdf.html"
        ]).render(context)
        order = HTML(string=html).render()

        # generate a pickup list
        html = select_template([
            "shop/reports/{}_vendor_pickup_list_pdf.html".format(vendor_title.replace(' ', '_').lower()),
            "shop/reports/vendor_pickup_list_pdf.html"
        ]).render(context)
        pickuplist = HTML(string=html).render()

        yield VendorOrder(order, pickuplist, vendor_title, vendor)


def generate_ffcsa_inventory_packlist(date, qs):
    """
    Generate a picklist for ffcsa_inventory products that are not on the
    grains & bean packlist or the frozen item packlist
    """
    # exclude_filter = Q()
    # for cat in settings.FROZEN_PRODUCT_CATEGORIES:  # + settings.GRAIN_BEANS_CATEGORIES:
    #     exclude_filter = exclude_filter | Q(category__icontains=cat)
    # filter = Q(in_inventory=True, is_frozen=False) & ~exclude_filter
    filter = Q(in_inventory=True)
    items = qs.filter(filter).order_by('category', 'description')
    context = {
        "items": items,
        "date": date,
    }
    html = get_template("shop/reports/ffcsa_inventory_packlist_pdf.html").render(context)
    return HTML(string=html).render()


def generate_dairy_packlist(date):
    items = OrderItem.objects \
        .filter(order__time__date=date, category__icontains='raw dairy') \
        .select_related('order') \
        .order_by('order__drop_site', 'order__billing_detail_last_name', 'order__billing_detail_first_name',
                  'description')
    order_items = OrderedDict()
    for k, v in groupby(items, key=lambda x: x.order.drop_site):
        i = OrderedDict()
        for k2, v2 in groupby(v, key=lambda x: (x.order.billing_detail_last_name, x.order.billing_detail_first_name)):
            i[k2] = list(v2)

        order_items[k] = i

    context = {
        'items': order_items,
        'date': date
    }

    html = get_template("shop/reports/dairy_packlist_pdf.html").render(context)
    return HTML(string=html).render()


def generate_frozen_items_report(date, qs):
    items = get_frozen_items(qs)
    context = {
        "items": items,
        "date": date,
    }
    html = get_template("shop/reports/dff_order_ticket_pdf.html").render(context)
    return HTML(string=html).render()


def get_frozen_items(qs, exclude_filter=Q()):
    """
    This should include the following:
       - any is_frozen items
       - any DFF item that is not in inventory and not in DFF_ORDER_TICKET_EXCLUDE_CATEGORIES
       - any item in FROZEN_PRODUCT_CATEGORIES
   """
    filter = Q()
    for cat in settings.FROZEN_PRODUCT_CATEGORIES:
        filter = filter | Q(category__icontains=cat)
    for cat in settings.DFF_ORDER_TICKET_EXCLUDE_CATEGORIES:
        exclude_filter = exclude_filter & ~Q(category__icontains=cat)
    exclude_filter = exclude_filter & Q(vendor__iexact='Deck Family Farm', in_inventory=False)
    filter = filter | exclude_filter
    filter = filter | Q(is_frozen=True)
    # we sort so we can use the django regroup filter
    items = qs.filter(filter).order_by('category', 'description')
    return items


def generate_frozen_items_packlist(date, qs):
    exclude_filter = Q()
    for cat in settings.FROZEN_ITEM_PACKLIST_EXCLUDED_CATEGORIES:
        exclude_filter = exclude_filter & ~Q(category__icontains=cat)
    items = get_frozen_items(
        qs.values('description', 'quantity', 'order__drop_site', 'order__billing_detail_last_name',
                  'order__billing_detail_first_name'),
        exclude_filter
    ).order_by('order__drop_site', 'order__billing_detail_last_name', 'order__billing_detail_first_name',
               'description')

    order_items = OrderedDict()
    for k, v in groupby(items, key=lambda x: x['order__drop_site']):
        i = OrderedDict()
        for k2, v2 in groupby(v, key=lambda x: (
        x['order__billing_detail_last_name'], x['order__billing_detail_first_name'])):
            i[k2] = list(v2)

        order_items[k] = i

    context = {
        'date': date
    }

    for drop_site, items in order_items.items():
        context.update({
            'drop_site': drop_site,
            'items': items,
            'num_of_orders': len(items)
        })
        html = get_template("shop/reports/frozen_item_packlist_pdf.html").render(context)
        yield HTML(string=html).render()


def generate_dff_dairy_packlist(date):
    items = OrderItem.objects \
        .filter(order__time__date=date, vendor__iexact='deck family farm', category__icontains='raw dairy') \
        .select_related('order') \
        .order_by('category', 'description')
    GroupedResult = namedtuple('GroupedResult', ['description', 'items', 'total_quantity'])
    order_items = []
    for key, val in groupby(items, key=lambda x: x.description):
        val = list(val)
        order_items.append(
            GroupedResult(description=key, items=val, total_quantity=sum([i.quantity for i in val]))
        )
    context = {
        'items': order_items,
        'date': date
    }
    html = get_template("shop/reports/dff_dairy_packlist_pdf.html").render(context)
    return HTML(string=html).render()


def generate_woven_roots_dairy_packlist(date):
    items = OrderItem.objects \
        .filter(order__time__date=date, vendor__iexact='woven roots', category__icontains='raw dairy') \
        .select_related('order') \
        .order_by('description')
    GroupedResult = namedtuple('GroupedResult', ['description', 'items'])
    order_items = [
        GroupedResult(description=key, items=list(val))
        for key, val in
        groupby(items, key=lambda x: x.description)
    ]
    context = {
        'items': order_items,
        'date': date
    }
    html = get_template("shop/reports/woven_roots_dairy_packlist_pdf.html").render(context)
    return HTML(string=html).render()


def generate_grain_and_bean_packlist(date):
    filter = Q()
    for cat in settings.GRAIN_BEANS_CATEGORIES:
        filter = filter | Q(category__icontains=cat)
    filter = Q(order__time__date=date, in_inventory=True) & filter
    items = OrderItem.objects \
        .filter(filter) \
        .select_related('order') \
        .order_by('description')
    GroupedResult = namedtuple('GroupedResult', ['description', 'items'])
    order_items = [
        GroupedResult(description=key, items=list(val))
        for key, val in
        groupby(items, key=lambda x: x.description)
    ]
    context = {
        'items': order_items,
        'date': date
    }
    html = get_template("shop/reports/grain_and_bean_packlist_pdf.html").render(context)
    return HTML(string=html).render()


def generate_product_order(date):
    filter = Q()
    for cat in settings.PRODUCT_ORDER_CATEGORIES:
        filter = filter | Q(category__icontains=cat)
    cart_items = OrderItem.objects.filter(filter, order__time__date=date, is_frozen=False).values('sku').distinct()
    qs = Product.objects.filter(variations__sku__in=cart_items)
    products = [p for p in qs]
    products.sort(key=product_keySort)

    context = {
        'products': products,
        'date': date,
    }

    html = get_template("shop/reports/product_order_list_pdf.html").render(context)
    return HTML(string=html).render()


def generate_home_delivery_notes(date):
    drop_site = 'Home Delivery'
    orders = Order.objects.filter(drop_site=drop_site, time__date=date,
                                  shipping_instructions__isnull=False) \
        .exclude(shipping_instructions__exact='') \
        .order_by('billing_detail_last_name', 'billing_detail_first_name')

    orders = list(orders)

    if len(orders) == 0:
        return

    html = get_template("shop/reports/home_delivery_instructions_pdf.html").render(
        {'orders': orders, 'drop_site': drop_site})
    return HTML(string=html).render()


def generate_home_delivery_checklists(date):
    drop_site = 'Home Delivery'

    annotations = {
        'last_name': F('billing_detail_last_name'),
        'first_name': F('billing_detail_first_name'),
        'shipping_street': F('shipping_detail_street'),
        'shipping_city': F('shipping_detail_city'),
        'shipping_ins': F('shipping_instructions'),
    }
    qs, columns = _get_market_checklist_qs(date, drop_site, annotations)

    qs = qs.values(*columns).order_by('billing_detail_last_name', 'billing_detail_first_name')
    users = list(qs)

    if len(users) == 0:
        return

    context = {
        'users': users,
        'headers': list(columns - annotations.keys()),
        'drop_site': drop_site,
        'date': date,
    }

    html = get_template("shop/reports/home_delivery_checklist_pdf.html").render(context)
    return HTML(string=html).render()


def generate_market_checklists(date):
    checklists = []

    for drop_site in settings.MARKET_CHECKLISTS:
        annotations = {
            'last_name': F('billing_detail_last_name'),
            'first_name': F('billing_detail_first_name'),
            'phone': F('billing_detail_phone'),
            'phone_2': F('billing_detail_phone_2'),
        }
        qs, columns = _get_market_checklist_qs(date, drop_site, annotations)

        qs = qs.values(*columns).order_by('last_name', 'first_name')
        users = list(qs)

        if len(users) == 0:
            continue

        for k in annotations.keys():
            columns.remove(k)

        context = {
            'users': users,
            'headers': columns,
            'drop_site': drop_site,
            'date': date,
        }

        html = get_template("shop/reports/market_checklist_pdf.html").render(context)
        checklists.append(HTML(string=html).render())

    if len(checklists) > 0:
        doc = checklists[0]

        pages = [p for doc in checklists for p in doc.pages]
        return doc.copy(pages)  # uses the metadata from doc


def _get_market_checklist_qs(date, drop_site, annotations):
    # checklist columns -> (category list, additional kwargs, default)
    qs = Order.objects.filter(drop_site__startswith=drop_site, time__date=date)  # .annotate(**annotations)
    annotates = OrderedDict(annotations)

    for column, (categories, kwargs, default) in settings.MARKET_CHECKLIST_COLUMN_CATEGORIES.items():
        filter = Q()
        for cat in categories:
            filter = filter | Q(category__icontains=cat)

        if kwargs and 'AND' in kwargs:
            filter = filter & Q(**kwargs['AND'])
        elif kwargs and 'OR' in kwargs:
            filter = filter | Q(**kwargs['OR'])

        if default is None:
            annotates[column] = Subquery(
                OrderItem.objects
                    .filter(filter, order_id=OuterRef('pk'))
                    .values('order_id')  # This provides a group_by order_id clause
                    .annotate(total=Sum('quantity'))
                    .values('total'),
                output_field=IntegerField(),
            )
        else:
            case = Case(
                When(total__gte=1, then=Value(default)),
                default=Value('0'),
                output_field=IntegerField())

            annotates[column] = Subquery(
                OrderItem.objects
                    .filter(filter, order_id=OuterRef('pk'))
                    .values('order_id')  # This provides a group_by order_id clause
                    .annotate(total=Sum('quantity'))
                    .annotate(has=case)
                    .values('has'),
                output_field=IntegerField(),
            )

    return qs.annotate(**annotates), list(annotates.keys())


def generate_master_checklist(date):
    qs = Order.objects.filter(time__date=date)

    annotations = OrderedDict()
    for column, (categories, kwargs, default) in settings.MARKET_CHECKLIST_COLUMN_CATEGORIES.items():
        filter = Q()
        for cat in categories:
            filter = filter | Q(category__icontains=cat)

        if kwargs and 'AND' in kwargs:
            filter = filter & Q(**kwargs['AND'])
        elif kwargs and 'OR' in kwargs:
            filter = filter | Q(**kwargs['OR'])

        if default is None:
            annotations[column] = Sum(
                Subquery(
                    OrderItem.objects
                        .filter(filter, order_id=OuterRef('pk'))
                        .values('order_id')  # This provides a group_by order_id clause
                        .annotate(total=Sum('quantity'))
                        .values('total'),
                    output_field=IntegerField(),
                )
            )
        else:
            case = Case(
                When(total__gte=1, then=Value(default)),
                default=Value('0'),
                output_field=IntegerField())

            annotations[column] = Sum(
                Subquery(
                    OrderItem.objects
                        .filter(filter, order_id=OuterRef('pk'))
                        .values('order_id')  # This provides a group_by order_id clause
                        .annotate(total=Sum('quantity'))
                        .annotate(has=case)
                        .values('has'),
                    output_field=IntegerField(),
                )
            )

    data = qs.values('drop_site').annotate(**annotations).order_by('drop_site')
    data = list(data)

    if len(data) == 0:
        return

    context = {
        'data': data,
        'headers': annotations.keys(),
        'date': date,
    }

    html = get_template("shop/reports/master_checklist_pdf.html").render(context)
    return HTML(string=html).render()


def send_order_to_vendor(order, vendor, vendor_title, date):
    """
    Attempt to email the order to the vendor if appropriate
    """

    to = (settings.DEFAULT_FROM_EMAIL,)
    bcc = (settings.DEFAULT_FROM_EMAIL,)
    subject = "FFCSA Order for {}".format(date)

    if vendor:
        if not vendor.auto_send_order:
            return
        to = (vendor.email,)
    else:
        subject = "URGENT FAILED TO SEND TO VENDOR: " + subject

    msg = EmailMessage(subject,
                       "Our order for {} is attached.\n\nThanks,\nThe FFCSA team".format(date),
                       settings.DEFAULT_FROM_EMAIL, to, bcc=bcc)
    msg.attach("{}_ffcsa_order_{}.pdf".format(vendor_title, date), order, mimetype='application/pdf')
    try:
        msg.send()
    except Exception as e:
        # Try to send attachment to ourselves
        logger.error(e)
        msg.subject = "URGENT FAILED TO SEND TO VENDOR: " + msg.subject
        msg.to = (settings.DEFAULT_FROM_EMAIL,)
        msg.cc = (settings.ADMINS[0][1],)

        try:
            msg.send()
        except Exception as e:
            # Try to send a notification to ourselves
            logger.error(e)
            EmailMessage("URGENT: FAILED TO SEND ORDER FOR {}".format(vendor_title),
                         "Was not able to send order attachment. You will need to manually send this",
                         settings.DEFAULT_FROM_EMAIL, msg.to, msg.cc).send()
