import requests
import logging
from django.contrib import auth
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.http import int_to_base36, urlencode
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.models import Site
from decimal import Decimal

from rest_framework import mixins, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import detail_route, list_route
from rest_framework.exceptions import NotFound
from mezzanine.utils.urls import next_url, unique_slug, slugify
from mezzanine.utils.email import subject_template
from signrequest_client.rest import ApiException

from ffcsa.core import signrequest
from ffcsa.core.api.permissions import IsOwner
from ffcsa.core.api.serializers import *
from ffcsa.core.google import add_contact as add_google_contact
from ffcsa.shop.models import Order
from ffcsa.core.models import Payment, DropSiteInfo
from ffcsa.core.subscriptions import *
from ffcsa.utils import DictClass

logger = logging.getLogger(__name__)

User = get_user_model()


class AppResources(viewsets.ViewSet):
    @list_route(methods=["post"])
    def get_drop_sites(self, request):
        return Response({"sites": settings.DROPSITES})


class UserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.all()
    permission_classes = [IsOwner]

    def list(self, request, *args, **kwargs):
        serializer = UserSerializer(request.user)
        response = {
            'id': request.user.id
        }
        response.update(serializer.data)
        return Response(response)

    def update(self, request, *args, **kwargs):
        user = get_object_or_404(User, pk=kwargs["pk"])
        profile_data = request.data.pop("profile")
        delivery_address = profile_data.get("delivery_address")

        # save user data
        serializer = UserSerializer(user, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # save user profile data
        serializer = ProfileSerializer(user.profile, data=profile_data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Save user delivery_address
        if profile_data.get("home_delivery"):
            profile = serializer.instance
            profile.delivery_address = delivery_address
            profile.save()

        return Response({})

    @detail_route(methods=["post"])
    def change_password(self, request, pk=None):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cpassword, password, password2 = serializer.data.values()

        if not request.user.check_password(cpassword):
            raise NotAcceptable("Wrong current password")

        if not password == password2:
            raise NotAcceptable("Could not confirm your new password")

        request.user.set_password(password)
        request.user.save()
        auth.authenticate(request.user)
        return Response({"detail": "Password updated"})


class SignupViewSet(viewsets.ViewSet):
    """Signup user"""

    serializer_class = SignupSerializer
    ignored_fields = ["num_children", "pickup_agreement", "communication_method", "best_time_to_reach"]

    def create(self, request):
        # extract user and profile info
        user_raw = request.data
        profile_raw = {k: v for (k, v) in request.data["profile"].items() if k not in self.ignored_fields and v != ""}

        # validate provided data (user/profile)
        user_serializer = SignupSerializer(data=user_raw)
        user_serializer.is_valid(raise_exception=True)

        profile_serializer = SignupProfileSerializer(data=profile_raw)
        profile_serializer.is_valid(raise_exception=True)

        # validate passwords match
        if not user_raw["password"] == user_raw["password2"]:
            raise NotAcceptable("Passwords do not match")

        if User.objects.filter(email=user_raw["email"]).count() > 0:
            raise NotAcceptable("A user with that email already exists.")

        user_data = user_serializer.data
        profile_data = profile_serializer.data

        # set blank username first
        user_data["username"] = ''

        # remove password2
        del user_data["password2"]

        with transaction.atomic():
            user = User.objects.create(**user_data)
            #hash the password
            user.set_password(user_data["password"])

            # set username
            username = user_data["first_name"] + '-' + user_data["last_name"]
            qs = User.objects.exclude(id=user.id)
            user.username = unique_slug(qs, "username", slugify(username))

            user.profile.__dict__.update(profile_data)

            # drop_site = self.cleaned_data['drop_site']
            # user.profile.drop_site = drop_site

            user.profile.notes = "<b>Best time to reach:</b>  {}<br/>" \
                                 "<b>Preferred communication method:</b>  {}<br/>" \
                                 "<b>Adults in family:</b>  {}<br/>" \
                                 "<b>Children in family:</b>  {}<br/>" \
                                 "<b>How did you hear about us:</b>  {}<br/>" \
                .format(request.data["profile"]['best_time_to_reach'],
                        request.data["profile"]['communication_method'],
                        request.data["profile"]['num_adults'],
                        request.data["profile"]['num_children'],
                        request.data["profile"]['hear_about_us'])

            # defaults
            user.profile.allow_substitutions = True
            user.profile.weekly_emails = True
            user.profile.plastic_bags = False

            user.profile.delivery_address = profile_data.get("delivery_address")
            sendinblue.update_or_add_user(user, sendinblue.NEW_USER_LISTS, sendinblue.NEW_USER_LISTS_TO_REMOVE)
            user.save()
            user.profile.save()

            # login user
            auth.login(request, user)

        # Send drop site information (or home delivery instructions)
        if settings.SENDINBLUE_ENABLED:
            params = {'FIRSTNAME': user.first_name}
            sib_template_name = 'Home Delivery' if user.profile.home_delivery else user.profile.drop_site

            date_last_modified = sendinblue.send_transactional_email(sib_template_name, user.email,
                                                                     params)

            # If the email is successfully sent add an appropriate DropSiteInfo to the user
            if date_last_modified is not False:
                _dropsite_info_obj = DropSiteInfo.objects.create(profile=user.profile,
                                                                 drop_site_template_name=sib_template_name,
                                                                 last_version_received=date_last_modified)
                _dropsite_info_obj.save()

            user.profile.save()

        c = {
            'user': "{} {}".format(user.first_name, user.last_name),
            'user_url': request.build_absolute_uri(reverse("admin:ffcsa_core_user_change", args=(user.id,))),
            'drop_site': 'Home Delivery' if user.profile.home_delivery else user.profile.drop_site,
            'phone_number': user.profile.phone_number,
            'phone_number_2': user.profile.phone_number_2,
            'email': user.email,
            'best_time_to_reach': request.data["profile"]['best_time_to_reach'],
            'communication_method': request.data["profile"]['communication_method'],
            'num_adults': request.data["profile"]['num_adults'],
            'num_children': request.data["profile"]['num_children'],
            'hear_about_us': request.data["profile"]['hear_about_us'],
            'payments_url': '{}?{}'.format(request.build_absolute_uri(reverse("profile_update")),
                                           urlencode({'section': 'payment'})),
        }

        try:
            signrequest.send_sign_request(user, True)
        except ApiException as e:
            # don't prevent the user from signing up. They can re-send the sign request document later
            logger.error(e)
        add_google_contact(user)

        subject = "New User Signup"
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
            user.email,
            context=c,
            fail_silently=False,
            addr_bcc=[settings.EMAIL_HOST_USER]
        )
        token, created = Token.objects.get_or_create(user=user)
        user_serializer = UserSerializer(user)

        return Response({"token": token.key, "user": user_serializer.data, "profile": user.profile.id})

    def update(self, request, *args, **kwargs):
        profile = get_object_or_404(Profile, pk=kwargs["pk"])
        join_dairy_program = request.data.get("join_dairy_program")

        try:
            profile_raw = ProfileSerializer(profile).data
            profile_raw['join_dairy_program'] = join_dairy_program
            profile_raw['delivery_address'] = ''

            serializer = ProfileSerializer(profile, data=profile_raw)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            return Response({})
        except Exception as e:
            raise NotAcceptable(e)


class LoginViewSet(viewsets.ViewSet):
    """Authenticate user and return user with token"""

    serializer_class = LoginSerializer

    def create(self, request):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        if user := auth.authenticate(**serializer.data):
            auth.login(request, user)
            token, created = Token.objects.get_or_create(user=user)
            user_serializer = UserSerializer(user)
            return Response({"token": token.key, "user": user_serializer.data})

        raise NotAcceptable("Invalid email or password")


class ResetPasswordViewSet(viewsets.ViewSet):

    def create(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if (user := User.objects.filter(email=serializer.data['email']).first()):
            try:
                # send_verification_mail(request, user, site_url, "password_reset_verify")
                site_url = settings.BASE_SITE_URL
                verification_type = "password_reset_verify"

                verify_url = (
                        reverse(
                            verification_type,
                            kwargs={
                                "uidb36": int_to_base36(user.id),
                                "token": default_token_generator.make_token(user),
                            },
                        )
                        + "?next="
                        + (next_url(request) or "/")
                )
                context = {
                    "request": request,
                    "user": user,
                    "verify_url": verify_url,
                    "site_url": site_url
                }
                subject_template_name = "email/%s_subject.txt" % verification_type
                subject = subject_template(subject_template_name, context)
                send_mail_template(
                    subject,
                    "email/%s" % verification_type,
                    settings.DEFAULT_FROM_EMAIL,
                    user.email,
                    context=context,
                )
            except Exception as ex:
                logging.error(ex)
                raise NotAcceptable("Something went wrong, try again later!")
            return Response({})

        raise NotFound("User not found")


class PaymentViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PaymentSerializer
    queryset = Payment.objects.order_by('-date')
    permission_classes = [IsAuthenticated]

    @list_route(methods=["get"])
    def only_payments(self, request):
        queryset = self.queryset.filter(user=request.user, is_credit=False)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @list_route(methods=["get"])
    def only_credits(self, request):
        queryset = self.queryset.filter(user=request.user, is_credit=True)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @list_route(methods=["post"])
    def update_payment_method(self, request):
        serializer = UpdatePaymentMethodSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.profile.stripe_customer_id or not user.profile.stripe_subscription_id:
            raise NotAcceptable('Could not find your subscription id to update. Please contact the site administrator.')

        try:
            payment_type = serializer.data.get("paymentType")
            stripe_token = serializer.data.get("stripeToken")
            if payment_type == 'CC':
                customer = stripe.Customer.retrieve(user.profile.stripe_customer_id)
                customer.source = stripe_token
                customer.save()
                # reset this so they don't receive error msg for failed ach verification
                user.profile.payment_method = 'CC'
                user.profile.ach_status = None
                user.profile.save()
                return Response({"detail": "Your payment method has been updated."})
            elif payment_type == 'ACH':
                customer = stripe.Customer.retrieve(user.profile.stripe_customer_id)
                customer.source = stripe_token
                customer.save()
                user.profile.payment_method = 'ACH'
                user.profile.ach_status = 'VERIFIED' if customer.sources.data[0].status == 'verified' else 'NEW'
                user.profile.save()
                return Response({"detail": "Your payment method has been updated."})
            else:
                raise NotAcceptable('Unknown Payment Type')

        except Exception as e:
            raise NotAcceptable(e)

    @list_route(methods=["post"])
    def update_monthly_contribution(self, request):
        serializer = UpdatePaymentAmountSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.profile.stripe_customer_id or not user.profile.stripe_subscription_id:
            raise NotAcceptable('Could not find your subscription id to update. Please contact the site administrator.')
        try:
            amount = serializer.data.get("amount")
            user.profile.monthly_contribution = Decimal(amount)
            update_stripe_subscription(user)
            user.profile.save()
            return Response({"detail": "Your monthly contribution has been updated."})

        except Exception as e:
            raise NotAcceptable(e)


class PayViewSet(viewsets.ViewSet):
    """Handels all types of user payments"""

    permission_classes = [IsAuthenticated]

    # TODO: handle permission classes here

    # quick checkout (non-members)
    @list_route(methods=["post"])
    def non_member_payment(self, request):
        serializer = NonMemberSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        try:
            res = stripe.Charge.create(
                amount=(int(serializer.data.get("amount") * 100)),  # in cents
                currency="usd",
                description=PAYMENT_DESCRIPTION,
                source="tok_visa",
                statement_descriptor=PAYMENT_DESCRIPTION,
            )

            # Payment will be created when the charge is successful
            return Response({"detail": "Your payment is pending"})

        except Exception as e:
            raise NotAcceptable(e.user_message)

    # >>>>>> make_payment
    @list_route(methods=["post"])
    def one_time_payment(self, request):
        """Make ont time payment using stripe Charge"""
        serializer = OneTimePaymentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        try:
            card = None
            if serializer.data.get("stripeToken", None):
                # create customer card
                customer = stripe.Customer.retrieve(request.user.profile.stripe_customer_id)
                card = customer.sources.create(source=serializer.data.get("stripeToken"))

            res = stripe.Charge.create(
                amount=(int(serializer.data.get("amount") * 100)),  # in cents
                currency="usd",
                description=PAYMENT_DESCRIPTION,
                customer=request.user.profile.stripe_customer_id,
                source=card.id if card else None,
                statement_descriptor=PAYMENT_DESCRIPTION,
            )

            # Payment will be created when the charge is successful
            return Response({"detail": "Your payment is pending"})

        except Exception as e:
            raise NotAcceptable(e.user_message)

    # >>>>>> verify_ach
    @list_route(methods=["post"])
    def verify_ach_deposits(self, request):
        serializer = VerifyACHDepositsSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        amount1, amount2 = serializer.data.values()
        customer = stripe.Customer.retrieve(user.profile.stripe_customer_id)
        bank_account = customer.sources.retrieve(customer.default_source)

        try:
            bank_account.verify(amounts=[int(amount1), int(amount2)])
            user.profile.ach_status = "VERIFIED"
            user.profile.save()

            # we can create the subscription right now
            if not user.profile.stripe_subscription_id:
                create_stripe_subscription(user)
                if not Payment.objects.filter(user=user).exists():
                    return Response(
                        {
                            "detail": "Your account has been verified and your first payment is processing. "
                                      "When your payment has been received, you will receive an email letting "
                                      "you know when your first ordering and pickup dates are. If you do not "
                                      "see this email in the next 5 - 7 business days, please check your spam"
                        }
                    )
                else:
                    subscription = stripe.Subscription.retrieve(user.profile.stripe_subscription_id)
                    next_payment_date = datetime.date.fromtimestamp(subscription.current_period_end + 1)
                    next_payment_date = formats.date_format(next_payment_date, "D, F d")
                    return Response(
                        {
                            "detail": "Congratulations, your account has been verified and your first payment is processing. "
                                      "You will be seeing this amount show up in your member store account in 5 - 7 business "
                                      "days. Your next scheduled payment will be " + next_payment_date
                        }
                    )
            else:
                return Response({"detail": "Your account has been verified."})

        except Exception as e:
            raise NotAcceptable(e.user_message)

    # >>>>>> payments_subscribe
    @list_route(methods=["post"])
    def subscribe(self, request):
        serializer = SubscribeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        amount, stripeToken, paymentType = serializer.data.values()

        if user.profile.join_dairy_program and not user.profile.paid_signup_fee:
            raise NotAcceptable("You must acknowledge the 1 time Raw Dairy program fee")

        try:
            if not user.profile.stripe_customer_id:
                # Absolutely new user
                customer = stripe.Customer.create(
                    email=user.email,
                    description=user.get_full_name(),
                    source=stripeToken,
                )
                user.profile.stripe_customer_id = customer.id

            else:
                # Resubscribed new user
                customer = stripe.Customer.retrieve(user.profile.stripe_customer_id)
                customer.source = stripeToken
                customer.save()
                sendinblue.on_user_resubscribe(user)

            # Update user profile
            user.profile.payment_method = paymentType
            user.profile.monthly_contribution = Decimal(amount)

            if paymentType == "ACH":
                user.profile.ach_status = "VERIFIED" if customer.sources.data[0].status == "verified" else "NEW"
                user.profile.save()
                return Response(
                    {
                        "detail": "Your subscription has been created. You will need to verify your bank account before your first payment is made."
                    }
                )
            elif paymentType == "CC":
                # we can create the subscription right now
                create_stripe_subscription(user)
                return Response(
                    {
                        "detail": "Your subscription has been created and your first payment is pending. You should see the payment credited to your account within the next few minutes"
                    }
                )

        except Exception as e:
            raise NotAcceptable(e)


class ContacUs(viewsets.ViewSet):
    def create(self, request):
        serializer = ContactUsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = DictClass(serializer.data)

        if data.target == "farm":
            TO_EMAIL = "info@deckfamilyfarm.com"

        if data.target == "csa":
            TO_EMAIL = "fullfarmcsa@deckfamilyfarm.com"

        HTML_CONTENT = f"""
        <html>
        <head></head>
        <body>
            <h4>New contact request</h4>
            <ul>
                <li>Name: {data.name}</li>
                <li>Email: {data.email}</li>
                <li>Phone: {data.phone}</li>
                <li>Message: {data.message}</li>
            </ul>
        </body>

        </html>
        
        """

        res = requests.post(
            "https://api.sendinblue.com/v3/smtp/email",
            json={
                "sender": {"name": "FFCSA Contact request", "email": "noreply@deckfamilyfarm.com"},
                "to": [{"email": TO_EMAIL}],
                "subject": "FFCSA Contact request",
                "htmlContent": HTML_CONTENT,
            },
            headers={
                "api-key": settings.SENDINBLUE_API_KEY,
                "accept": "application/json",
                "content-type": "application/json",
            },
        )

        return Response({"details": "sent"})


class LeadGenPDF(viewsets.ViewSet):
    def create(self, request):
        serializer = LeadGenPDFSerializer(data=request.data)
        serializer.is_valid()

        # Create new contact and add contact to list 59 "FFCSA Leads"
        data = DictClass(serializer.data)

        res = requests.post(
            "https://api.sendinblue.com/v3/contacts",
            json={
                "attributes": {"FIRSTNAME": data.first_name, "LASTNAME": data.last_name},
                "listIds": [59],
                "updateEnabled": True,
                "email": data.email,
            },
            headers={
                "api-key": settings.SENDINBLUE_API_KEY,
                "accept": "application/json",
                "content-type": "application/json",
            },
        )

        if res.status_code in [200, 201, 204]:
            # send back the pdf url
            pdf = "/static/pdf/DFF_Hogwash-or-Greenwash%20V03.pdf"
            return Response({"pdf": pdf})

        raise NotAcceptable("Something went wrong")


class Donate(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def create(self, request):
        user = request.user
        serializer = DonateSerializer(data=request.data)
        serializer.is_valid()

        amount = Decimal(serializer.data.get('amount'))

        ytd_contrib = Payment.objects.total_for_user(user)
        ytd_ordered = Order.objects.total_for_user(user)
        if not ytd_ordered:
            ytd_ordered = Decimal(0)
        if not ytd_contrib:
            ytd_contrib = Decimal(0)

        # get remaining_budget
        print("cart : ", request.cart.total_price())
        remaining_budget = float("{0:.2f}".format(ytd_contrib - ytd_ordered - request.cart.total_price()))

        if amount > Decimal(remaining_budget):
            raise NotAcceptable("You can not donate more then your remaining budget.")

        feed_a_friend, created = User.objects.get_or_create(username=settings.FEED_A_FRIEND_USER)

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

        return Response({"details": "Thank you for your donation to the Feed-A-Friend fund!"})
