import datetime
import logging
import json
from decimal import Decimal

import stripe
from dal import autocomplete
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.messages import error, info, success
from django.contrib.sites.models import Site
from django.db.models import Q
from django.forms import modelformset_factory
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import HttpResponse, TemplateResponse
from django.urls import reverse
from django.utils import formats
from django.utils.decorators import method_decorator
from django.utils.http import is_safe_url
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST
from django.views import View
from django_common import http
from mezzanine.conf import settings
from mezzanine.core.models import CONTENT_STATUS_PUBLISHED
from mezzanine.utils.email import send_mail_template
from mezzanine.utils.views import paginate
from mezzanine.accounts import views
from signrequest_client.rest import ApiException

from ffcsa.core.dropsites import get_full_drop_locations
from ffcsa.shop.actions.order_actions import DEFAULT_GROUP_KEY
from ffcsa.shop.models import Category, Order, Product
from ffcsa.core.forms import BasePaymentFormSet, ProfileForm, CreditOrderedProductForm
from ffcsa.core.google import add_contact as add_google_contact
from ffcsa.core import sendinblue, signrequest
from ffcsa.core.models import Payment, Recipe
from ffcsa.core.subscriptions import (SIGNUP_DESCRIPTION,
                                      clear_ach_payment_source,
                                      create_stripe_subscription,
                                      send_failed_payment_email,
                                      send_first_payment_email,
                                      send_pending_payment_email,
                                      send_subscription_canceled_email,
                                      update_stripe_subscription, PAYMENT_DESCRIPTION, MEMBERSHIP_PAYMENT_DESCRIPTION)
from ffcsa.shop.utils import set_home_delivery, clear_shipping

from .utils import (ORDER_CUTOFF_DAY, next_weekday)

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)


def shop_home(request, template="shop_home.html"):
    root_categories = Category.objects.published().filter(
        Q(products__available=True) | Q(
            id__in=Category.objects.filter(parent__isnull=False).values('parent_id').distinct()),
        parent__isnull=True
    ).distinct()
    recipes = Recipe.objects.published().filter(slug='recipes').first()

    context = {
        'categories': root_categories,
        'recipes': recipes,
        'settings': settings,
    }

    return TemplateResponse(request, template, context)


def signup(request, template="accounts/account_signup.html", extra_context=None):
    """
    signup view.
    """

    form = ProfileForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        new_user = form.save()
        info(request, "Successfully signed up")
        auth_login(request, new_user)

        c = {
            'user': "{} {}".format(new_user.first_name, new_user.last_name),
            'user_url': request.build_absolute_uri(reverse("admin:auth_user_change", args=(new_user.id,))),
            'drop_site': 'Home Delivery' if new_user.profile.home_delivery else form.cleaned_data.get('drop_site'),
            'phone_number': form.cleaned_data['phone_number'],
            'phone_number_2': form.cleaned_data['phone_number_2'],
            'email': form.cleaned_data.get('email', ''),
            'join_dairy_program': new_user.profile.join_dairy_program,
            'best_time_to_reach': form.cleaned_data['best_time_to_reach'],
            'communication_method': form.cleaned_data['communication_method'],
            'num_adults': form.cleaned_data['num_adults'],
            'num_children': form.cleaned_data['num_children'],
            'hear_about_us': form.cleaned_data['hear_about_us'],
            'payments_url': request.build_absolute_uri(reverse("payments")),
        }

        try:
            signrequest.send_sign_request(new_user, True)
        except ApiException as e:
            # don't prevent the user from signing up. They can re-send the sign request document later
            logger.error(e)
        add_google_contact(new_user)

        subject = "New User Signup"
        if new_user.profile.join_dairy_program:
            subject = subject + ' - Needs Dairy Conversation'
        send_mail_template(
            subject,
            "ffcsa_core/send_admin_new_user_email",
            settings.DEFAULT_FROM_EMAIL,
            settings.ACCOUNTS_APPROVAL_EMAILS,
            context=c,
            fail_silently=True,
        )
        send_mail_template(
            "Congratulations on your new Full Farm CSA account!",
            "ffcsa_core/send_new_user_email",
            settings.DEFAULT_FROM_EMAIL,
            new_user.email,
            context=c,
            fail_silently=False,
            addr_bcc=[settings.EMAIL_HOST_USER]
        )

        return HttpResponseRedirect(reverse('payments'))

    context = {"form": form, "title": "Join Now!"}
    context.update(extra_context or {})
    return TemplateResponse(request, template, context)


@login_required
def payments(request, template="ffcsa_core/payments.html", extra_context=None):
    """
    Display a list of the currently logged-in user's past orders.
    """

    extra_context = {} if extra_context is None else extra_context

    next_payment_date = None
    if request.user.profile.stripe_subscription_id:
        subscription = stripe.Subscription.retrieve(request.user.profile.stripe_subscription_id)
        next_payment_date = datetime.date.fromtimestamp(subscription.current_period_end + 1)
        next_payment_date = formats.date_format(next_payment_date, "D, F d")

    elif settings.DEBUG:
        next_payment_date = datetime.datetime.today() + datetime.timedelta(days=62)
        next_payment_date = formats.date_format(next_payment_date, "D, F d")

    all_payments = Payment.objects.filter(user__id=request.user.id)
    payments = paginate(all_payments.order_by('-date', '-id'),
                        request.GET.get("page", 1),
                        settings.SHOP_PER_PAGE_CATEGORY,
                        settings.MAX_PAGING_LINKS)
    context = {"payments": payments,
               "contact_email": settings.DEFAULT_FROM_EMAIL,
               "next_payment_date": next_payment_date,
               "subscribe_errors": request.GET.getlist('error'),
               "STRIPE_API_KEY": settings.STRIPE_API_KEY}
    context.update(extra_context)

    return TemplateResponse(request, template, context)


@require_POST
@login_required
def payments_subscribe(request):
    """
    Create a new subscription
    """
    errors = []
    amount = Decimal(request.POST.get('amount'))
    paymentType = request.POST.get('paymentType')
    stripeToken = request.POST.get('stripeToken')

    user = request.user
    if user.profile.join_dairy_program and not user.profile.paid_signup_fee and not request.POST.get(
            'signupAcknowledgement') == 'True':
        errors.append('You must acknowledge the 1 time Dairy program fee')

    if not stripeToken:
        errors.append('Invalid Request')

    try:
        if not errors:
            resubscribed = False

            if paymentType == 'CC':
                if not user.profile.stripe_customer_id:
                    customer = stripe.Customer.create(
                        email=user.email,
                        description=user.get_full_name(),
                        source=stripeToken,
                    )
                    user.profile.stripe_customer_id = customer.id

                else:
                    customer = stripe.Customer.retrieve(user.profile.stripe_customer_id)
                    customer.source = stripeToken
                    customer.save()

                    resubscribed = True

                user.profile.payment_method = 'CC'
                user.profile.monthly_contribution = amount
                user.profile.save()

                # we can create the subscription right now
                create_stripe_subscription(user)
                success(request,
                        'Your subscription has been created and your first payment is pending. '
                        'You should see the payment credited to your account within the next few minutes')

            elif paymentType == 'ACH':
                if not user.profile.stripe_customer_id:
                    customer = stripe.Customer.create(
                        email=user.email,
                        description=user.get_full_name(),
                        source=stripeToken,
                    )
                    user.profile.stripe_customer_id = customer.id

                else:
                    customer = stripe.Customer.retrieve(
                        user.profile.stripe_customer_id)
                    customer.source = stripeToken
                    customer.save()

                    resubscribed = True

                user.profile.payment_method = 'ACH'
                user.profile.monthly_contribution = amount
                user.profile.ach_status = 'VERIFIED' if customer.sources.data[
                                                            0].status == 'verified' else 'NEW'
                user.profile.save()
                success(request,
                        'Your subscription has been created. You will need to verify your bank account '
                        'before your first payment is made.')

            else:
                errors.append('Unknown Payment Type')

            if resubscribed:
                sendinblue.on_user_resubscribe(user)

    except stripe.error.CardError as e:
        body = e.json_body
        err = body.get('error', {})
        errors.append(err.get('message'))

    url = reverse('payments')
    isFirst = True
    for error in errors:
        if isFirst:
            url += "?error={}".format(error)
        else:
            url += "&error={}".format(error)

    return HttpResponseRedirect(url)


@require_POST
@login_required
def payments_update(request):
    """
    Update a payment source
    """
    errors = []
    paymentType = request.POST.get('paymentType')
    stripeToken = request.POST.get('stripeToken')

    user = request.user
    if not user.profile.stripe_customer_id or not user.profile.stripe_subscription_id:
        errors.append(
            'Could not find your subscription id to update. Please contact the site administrator.')

    if not stripeToken:
        errors.append('Invalid Request')

    try:
        if not errors:
            if paymentType == 'CC':
                customer = stripe.Customer.retrieve(
                    user.profile.stripe_customer_id)
                customer.source = stripeToken
                customer.save()
                # reset this so they don't receive error msg for failed ach verification
                user.profile.payment_method = 'CC'
                user.profile.ach_status = None
                user.profile.save()
                success(request, 'Your payment method has been updated.')
            elif paymentType == 'ACH':
                customer = stripe.Customer.retrieve(
                    user.profile.stripe_customer_id)
                customer.source = stripeToken
                customer.save()
                user.profile.payment_method = 'ACH'
                user.profile.ach_status = 'VERIFIED' if customer.sources.data[
                                                            0].status == 'verified' else 'NEW'
                user.profile.save()
                success(request, 'Your payment method has been updated.')
            else:
                errors.append('Unknown Payment Type')

    except stripe.error.CardError as e:
        body = e.json_body
        err = body.get('error', {})
        errors.append(err.get('message'))

    url = reverse('payments')
    isFirst = True
    for error in errors:
        if isFirst:
            url += "?error={}".format(error)
        else:
            url += "&error={}".format(error)

    return HttpResponseRedirect(url)


@require_POST
@login_required
def payments_update_amount(request):
    """
    Update subscription amount
    """
    errors = []
    amount = Decimal(request.POST.get('amount'))

    user = request.user
    if not user.profile.stripe_customer_id or not user.profile.stripe_subscription_id:
        errors.append(
            'Could not find your subscription id to update. Please contact the site administrator.')

    if not errors and amount != user.profile.monthly_contribution:
        user.profile.monthly_contribution = amount
        update_stripe_subscription(user)
        user.profile.save()
        success(request, 'Your monthly contribution has been updated.')

    url = reverse('payments')
    isFirst = True
    for error in errors:
        if isFirst:
            url += "?error={}".format(error)
        else:
            url += "&error={}".format(error)

    return HttpResponseRedirect(url)


@require_POST
@login_required
def make_payment(request):
    """
    Make a 1 time payment
    """
    hasError = False
    amount = Decimal(request.POST.get('amount', 0))

    user = request.user
    if not user.profile.stripe_customer_id:
        hasError = True
        error(request, 'Could not find a valid customer id. Please contact the site administrator.')

    if not request.POST.get('chargeAcknowledgement') == 'True':
        hasError = True
        error(request, 'You must acknowledge the charge')

    if not amount:
        hasError = True
        error(request, 'Invalid amount provided.')

    if amount < 20:
        hasError = True
        error(request, 'Minimum payment amount is $20.')

    try:
        if not hasError:
            stripeToken = request.POST.get('stripeToken')
            card = None
            if stripeToken:
                customer = stripe.Customer.retrieve(
                    user.profile.stripe_customer_id)
                card = customer.sources.create(source=stripeToken)

            stripe.Charge.create(
                amount=(amount * 100).quantize(0),  # in cents
                currency='usd',
                description=PAYMENT_DESCRIPTION,
                customer=user.profile.stripe_customer_id,
                source=card.id if card else None,
                statement_descriptor=PAYMENT_DESCRIPTION,
            )
            success(request, 'Your payment is pending.')
            # Payment will be created when the charge is successful

    except stripe.error.CardError as e:
        body = e.json_body
        err = body.get('error', {})
        error(request, err.get('message'))

    return HttpResponseRedirect(reverse('payments'))


@require_POST
@login_required
def donate(request):
    """
    Make a 1 donation to the feed a friend fund
    """
    hasError = False
    amount = Decimal(request.POST.get('amount'))

    user = request.user
    if not amount:
        hasError = True
        error(request, 'Invalid amount provided.')

    if amount > Decimal(request.session["remaining_budget"]):
        hasError = True
        error(request, 'You can not donate more then your remaining budget.')

    if not hasError:
        feed_a_friend, created = User.objects.get_or_create(
            username=settings.FEED_A_FRIEND_USER)

        # TODO :: Ensure this works for non-subscribing members
        order_dict = {
            'user_id': user.id,
            'time': datetime.datetime.now(),
            'site': Site.objects.get(id=1),
            'billing_detail_first_name': user.first_name,
            'billing_detail_last_name': user.last_name,
            'billing_detail_email': user.email,
            'billing_detail_phone': user.profile.phone_number,
            'billing_detail_phone_2': user.profile.phone_number_2,
            'total': amount,
        }

        order = Order.objects.create(**order_dict)

        item_dict = {
            'sku': 0,
            'description': 'Feed-A-Friend Donation',
            'quantity': 1,
            'unit_price': amount,
            'total_price': amount,
            'category': 'Feed-A-Friend',
            'vendor': 'Feed-A-Friend',
            'vendor_price': 0,
        }

        order.items.create(**item_dict)
        Payment.objects.create(amount=amount, user=feed_a_friend, is_credit=True,
                               notes="Donation from {}".format(user.get_full_name()))
        success(request, 'Thank you for your donation to the Feed-A-Friend fund!')

    next = request.GET.get('next', '/')
    # check that next is safe
    if not is_safe_url(next):
        next = '/'
    return HttpResponseRedirect(next)


@require_POST
@login_required
def verify_ach(request):
    """
    Verify an ACH bank account
    """
    errors = []
    amount1 = request.POST.get('amount1')
    amount2 = request.POST.get('amount2')
    user = request.user

    if not amount1 or not amount2:
        errors.append('both amounts are required')

    if not user.profile.stripe_customer_id:
        errors.append(
            'You are missing a customerId. Please contact the site administrator')

    if not errors:
        customer = stripe.Customer.retrieve(user.profile.stripe_customer_id)
        bank_account = customer.sources.retrieve(customer.default_source)

        amount1 = amount1.split('.')[-1]
        amount2 = amount2.split('.')[-1]

        # verify the account
        try:
            bank_account.verify(amounts=[amount1, amount2])
            user.profile.ach_status = 'VERIFIED'
            user.profile.save()

            # we can create the subscription right now
            if not user.profile.stripe_subscription_id:
                create_stripe_subscription(user)
                if not Payment.objects.filter(user=user).exists():
                    success(request,
                            'Your account has been verified and your first payment is processing. '
                            'When your payment has been received, you will receive an email letting '
                            'you know when your first ordering and pickup dates are. If you do not '
                            'see this email in the next 5 - 7 business days, please check your spam')
                else:
                    subscription = stripe.Subscription.retrieve(
                        user.profile.stripe_subscription_id)
                    next_payment_date = datetime.date.fromtimestamp(
                        subscription.current_period_end + 1)
                    next_payment_date = formats.date_format(
                        next_payment_date, "D, F d")
                    success(request,
                            'Congratulations, your account has been verified and your first payment is processing. '
                            'You will be seeing this amount show up in your member store account in 5 - 7 business '
                            'days. Your next scheduled payment will be ' + next_payment_date)
            else:
                success(request, 'Your account has been verified.')
        except stripe.error.CardError as e:
            user.profile.ach_status = 'VERIFYING'
            user.profile.save()
            body = e.json_body
            err = body.get('error', {})
            error(request, err.get('message'))

    url = reverse('payments')
    isFirst = True
    for e in errors:
        if isFirst:
            url += "?error={}".format(e)
        else:
            url += "&error={}".format(e)

    return HttpResponseRedirect(url)


@require_POST
@csrf_exempt
def stripe_webhooks(request):
    """
    endpoint for handling stripe webhooks
    """
    # Retrieve the request's body and parse it as JSON:
    payload = request.body
    sig_header = request.META['HTTP_STRIPE_SIGNATURE']

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_ENDPOINT_SECRET
        )

        if event.type == 'charge.pending':
            user = User.objects.filter(
                profile__stripe_customer_id=event.data.object.customer).first()
            charge = event.data.object
            # only save pending ach transfers. cc payments are basically instant
            if user and charge.source.object == 'bank_account' and charge.description != SIGNUP_DESCRIPTION:
                amount = charge.amount / 100  # amount is in cents
                date = datetime.datetime.fromtimestamp(charge.created)
                existing_payments = Payment.objects.filter(charge_id=charge.id)
                if existing_payments.exists():
                    raise AssertionError(
                        "Pending Payment Error: That payment already exists: {}".format(existing_payments.first()))
                else:
                    payment = Payment.objects.create(user=user, amount=amount, date=date, charge_id=charge.id,
                                                     pending=True)
                    payment.save()
                    payments_url = request.build_absolute_uri(
                        reverse("payments"))
                    send_pending_payment_email(user, payments_url)

            elif not user:
                logger.error('Failed to find user with stripe_customer_id: ', event.data.object.customer)

        elif event.type == 'charge.succeeded':
            # TODO :: Will non-users get an email when the payment processes?
            # TODO :: Will non-users get processed at all?

            user = User.objects.filter(profile__stripe_customer_id=event.data.object.customer).first()
            charge = event.data.object

            if user:
                if charge.description == SIGNUP_DESCRIPTION:
                    user.profile.paid_signup_fee = True
                    user.profile.save()

                else:
                    amount = charge.amount / 100  # amount is in cents
                    date = datetime.datetime.fromtimestamp(charge.created)
                    existing_payments = Payment.objects.filter(charge_id=charge.id)

                    if existing_payments.filter(pending=False).exists():
                        raise AssertionError(
                            "That payment already exists: {}".format(existing_payments.filter(pending=False).first()))

                    else:
                        sendFirstPaymentEmail = not Payment.objects.filter(user=user).exists()
                        payment = existing_payments.filter(pending=True).first()

                        if payment is None:
                            payment = Payment.objects.create(user=user, amount=amount, date=date, charge_id=charge.id)
                        else:
                            payment.pending = False

                        payment.save()

                        if sendFirstPaymentEmail:
                            user.profile.start_date = date
                            user.profile.save()
                            send_first_payment_email(user)
            elif charge.statement_descriptor in [SIGNUP_DESCRIPTION, MEMBERSHIP_PAYMENT_DESCRIPTION,
                                                 PAYMENT_DESCRIPTION]:
                logger.error('Failed to find user with stripe_customer_id: ', event.data.object.customer)

        elif event.type == 'charge.failed':
            user = User.objects.filter(
                profile__stripe_customer_id=event.data.object.customer).first()
            charge = event.data.object
            err = charge.failure_message
            payments_url = request.build_absolute_uri(reverse("payments"))
            created = datetime.datetime.fromtimestamp(
                charge.created).strftime('%d-%m-%Y')
            send_failed_payment_email(
                user, err, charge.amount / 100, created, payments_url)

        elif event.type == 'customer.source.updated' and event.data.object.object == 'bank_account':
            user = User.objects.filter(
                profile__stripe_customer_id=event.data.object.customer).first()
            if user.profile.ach_status == 'NEW' and event.data.object.status == 'verification_failed':
                # most likely wrong account info was entered
                clear_ach_payment_source(user, event.data.object.id)

        elif event.type == 'customer.subscription.deleted':
            user = User.objects.filter(
                profile__stripe_customer_id=event.data.object.customer).first()
            user.profile.stripe_subscription_id = None
            user.profile.save()
            date = datetime.datetime.fromtimestamp(
                event.data.object.canceled_at).strftime('%d-%m-%Y')
            payments_url = request.build_absolute_uri(reverse("payments"))
            send_subscription_canceled_email(user, date, payments_url)

            sendinblue.on_user_cancel_subscription(user)

    except ValueError as e:
        logger.error('Stripe webhook value error: ', e)
        # Invalid payload
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return HttpResponse(status=400)

    # Do something with event

    return HttpResponse(status=200)


#############
# Custom Admin Views
#############

@staff_member_required
def admin_attending_dinner(request, template="admin/attending_dinner.html"):
    today = datetime.date.today()

    # TODO fixme
    if today.weekday() < ORDER_CUTOFF_DAY:
        delta = ORDER_CUTOFF_DAY - today.weekday()
        order_date = today + datetime.timedelta(delta) - datetime.timedelta(7)
    else:
        delta = today.weekday() - ORDER_CUTOFF_DAY
        order_date = today - datetime.timedelta(delta)

    last_week_orders = Order.objects \
        .filter(time__gte=order_date).order_by('billing_detail_last_name')

    attendees = [{'family': o.billing_detail_last_name, 'attending_dinner': o.attending_dinner}
                 for o in last_week_orders if o.attending_dinner > 0]

    context = {
        'attendees': attendees
    }

    return TemplateResponse(request, template, context)


User = get_user_model()


@staff_member_required
def admin_member_budgets(request, template="admin/member_budgets.html"):
    users = User.objects.filter(is_active=True).order_by('last_name')

    budgets = []

    for user in users:
        ytd_contrib = Payment.objects.total_for_user(user)
        ytd_ordered = Order.objects.total_for_user(user)
        if not ytd_ordered:
            ytd_ordered = Decimal(0)
        if not ytd_contrib:
            ytd_contrib = Decimal(0)
        budgets.append({
            'user': user,
            'ytd_contrib': "{0:.2f}".format(ytd_contrib),
            'ytd_ordered': ytd_ordered,
            'budget': "{0:.2f}".format(ytd_contrib - ytd_ordered)
        })

    context = {
        'budgets': budgets
    }

    return TemplateResponse(request, template, context)


@staff_member_required
def member_order_history(request, template="admin/member_order_history.html"):
    users = User.objects.filter(is_active=True).order_by('last_name')

    data = []

    # TODO fixme
    now = datetime.datetime.now()
    next_order_day = next_weekday(now, ORDER_CUTOFF_DAY)  # get the order day

    wk = next_order_day - datetime.timedelta(7)
    weeks = [wk]

    # go back 8 weeks
    while wk > next_order_day - datetime.timedelta(8 * 7):
        wk = wk - datetime.timedelta(7)
        weeks.append(wk)

    weeks.reverse()

    for user in users:
        orders = Order.objects.filter(user_id=user.id, time__gte=datetime.datetime(wk.year, wk.month, wk.day)).order_by(
            'time')
        sum = 0
        num_orders = 0

        order_totals = []

        i = 0
        for order in orders:
            while i < len(weeks) and weeks[i].date() < order.time.date():
                order_totals.append(0)
                i += 1

            if i >= len(weeks):
                break

            if weeks[i].date() == order.time.date():
                order_totals.append(order.total.quantize(Decimal('.00')))
                sum += order.total
                num_orders += 1
            else:
                order_totals.append(0)

            i += 1

        while len(order_totals) < len(weeks):
            order_totals.append(0)

        data.append({
            'user': user,
            'orders': order_totals,
            'avg': 0 if sum == 0 else Decimal(sum / num_orders).quantize(Decimal('.00'))
        })

    context = {
        'data': data,
        'weeks': weeks
    }

    return TemplateResponse(request, template, context)


@csrf_protect
@staff_member_required
def admin_bulk_payments(request, template="admin/bulk_payments.html"):
    ids = request.GET.get('ids', [])
    if ids and isinstance(ids, str):
        ids = ids.split(',')

    extra = 1 if len(ids) > 0 else 2
    can_delete = len(ids) > 0

    PaymentFormSet = modelformset_factory(Payment, fields=('user', 'date', 'amount', 'notes', 'is_credit'),
                                          can_delete=can_delete,
                                          extra=extra, formset=BasePaymentFormSet)

    if request.method == 'POST':
        formset = PaymentFormSet(request.POST, request=request)
        if formset.is_valid():
            formset.save()
            return HttpResponseRedirect(reverse('admin:ffcsa_core_payment_changelist'))

    PaymentFormSet.form.base_fields['user'].queryset = User.objects.filter(
        is_active=True).order_by('last_name')
    formset = PaymentFormSet(queryset=Payment.objects.filter(pk__in=ids))

    setattr(formset, 'opts', {
        'verbose_name_plural': 'Payments',
        'model_name': 'Payment'
    })
    context = {
        'formset': formset,
        'change': False,
        'is_popup': False,
        'to_field': False,
        'save_on_top': False,
        'save_as': True,
        'show_save_and_continue': False,
        'has_delete_permission': False,
        'show_delete': False,
        'has_add_permission': True,
        'has_change_permission': True,
        'add': False
    }
    return TemplateResponse(request, template, context)


def product_keySort(product):
    """ If updating, make sure to update keySort function in order_actions.py"""
    if product.order_on_invoice:
        return (product.order_on_invoice, product.title)

    cat = product.get_category()

    if cat and not cat.parent:
        return (cat.order_on_invoice, product.title)

    if cat and cat.parent and cat.parent.category:
        parent_order = cat.parent.category.order_on_invoice
        order = cat.order_on_invoice
        if order == 0:
            order = DEFAULT_GROUP_KEY

        return (
            float("{}.{}".format(parent_order, order)),
            product.title
        )
    # just return a default number for category
    return (DEFAULT_GROUP_KEY, product.title)


@csrf_protect
@staff_member_required
def admin_product_invoice_order(request, template="admin/product_invoice_order.html"):
    products = [p for p in Product.objects.filter(
        available=True, status=CONTENT_STATUS_PUBLISHED)]

    for p in products:
        p.computed_order_on_invoice = product_keySort(p)[0]

    products.sort(key=product_keySort)

    context = {
        'products': products,
    }

    return TemplateResponse(request, template, context)


@csrf_protect
@staff_member_required
def admin_credit_ordered_product(request, template="admin/credit_ordered_product.html"):
    form = CreditOrderedProductForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        date = form.cleaned_data.get('date')
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
        products = form.cleaned_data.get('products')
        credits = []

        orders_to_credit = Order.objects.prefetch_related('items').filter(time__gte=date,
                                                                          time__lt=date + datetime.timedelta(days=1),
                                                                          items__description__in=products).exclude(
            user_id__isnull=True).distinct()

        base_msg = 'missing products on {}'.format(date)
        for o in orders_to_credit:
            amt = 0
            items = []
            for i in o.items.filter(description__in=products):
                items.append(i.description)
                amt = amt + i.total_price
            credits.append(Payment(user_id=o.user_id, notes='{}: {}'.format(base_msg, ' & '.join(items)), amount=amt,
                                   is_credit=True))

        Payment.objects.bulk_create(credits)
        success(request, "Successfully credited {} members".format(len(credits)))

        if form.cleaned_data.get('notify', False):
            # send email
            for p in credits:
                send_mail_template(
                    "FFCSA Credit",
                    "ffcsa_core/ordered_product_applied_credit_email",
                    settings.DEFAULT_FROM_EMAIL,
                    p.user.email,
                    fail_silently=True,
                    context={
                        'first_name': p.user.first_name,
                        'date': date,
                        'amount': p.amount,
                        'product_msg': p.notes.split(':')[1],
                        'msg': form.cleaned_data.get('msg', None),
                        'payments_url': request.build_absolute_uri(reverse("payments"))
                    }
                )

        return HttpResponseRedirect(reverse('admin:ffcsa_core_payment_changelist'))

    context = {
        'form': form,
    }

    return TemplateResponse(request, template, context)


@login_required
def profile_update(request, template="accounts/account_profile_update.html",
                   extra_context=None):
    res = views.profile_update(request, template, extra_context)

    # Since we don't have access to the request in the ProfileForm, we do this here
    if request.user.profile.home_delivery:
        set_home_delivery(request)
    else:
        clear_shipping(request)

    return res


class ProductAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        qs = Product.objects.filter(
            available=True, status=CONTENT_STATUS_PUBLISHED)

        if self.q:
            qs = qs.filter(title__icontains=self.q)

        return qs


def home_delivery_check(request, zip):
    return http.JsonResponse(
        {
            'is_full': zip in get_full_drop_locations()
        })


@method_decorator(csrf_exempt, name='dispatch')
class SignRequest(View):
    http_method_names = ['get', 'post']

    @method_decorator(login_required)
    def get(self, request):
        """Re-sends a SignRequest"""
        try:
            signrequest.send_sign_request(request.user)
            messages.success(request, 'We have sent a copy of our Membership Agreement to your email.')
        except signrequest.DocSignedError:
            messages.info(request,
                          'You have already signed the agreement. Please refresh the page and contact fullfarmcsa@deckfamilyfarm.com if are still asked to sign the membership agreement.')
        except ApiException:
            messages.error(request,
                           'There was an error sending the agreement. If this continues to occur, please contact fullfarmcsa@deckfamilyfarm.com and we will help you out.')

        referer = request.META.get('HTTP_REFERER', None)
        if referer and request.get_host() in referer:
            return redirect(request.META['HTTP_REFERER'])

        return redirect(reverse('home'))

    def post(self, request):
        return signrequest.handle_webhook(json.loads(request.body.decode()))
