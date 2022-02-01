import datetime
import requests
import stripe
from django.contrib import auth
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.conf import settings

from rest_framework import mixins
from rest_framework import viewsets
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import detail_route, list_route, permission_classes
from rest_framework.exceptions import NotAcceptable

from ffcsa.core import sendinblue
from ffcsa.core.api.permissions import IsOwner, CanPay
from ffcsa.core.api.serializers import *
from ffcsa.core.models import Payment, Address
from ffcsa.core.subscriptions import *
from ffcsa.utils import DictClass


User = get_user_model()


class AppResources(viewsets.ViewSet):
    @list_route(methods=["post"])
    def get_drop_sites(self, request):
        return Response({"sites": settings.DROPSITES})


class UserViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.all()
    permission_classes = [IsAuthenticated, IsOwner]

    def update(self, request, *args, **kwargs):
        user = get_object_or_404(User, pk=kwargs["pk"])
        profile_data = request.data.pop("profile")
        delivery_address = profile_data.pop("delivery_address")

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
        # extract user and profle info
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

        user_data = user_serializer.data
        profile_data = profile_serializer.data

        # remove password2
        del user_data["password2"]

        with transaction.atomic():
            user = User.objects.create(**user_data)
            user.profile.__dict__.update(profile_data)

            user.profile.delivery_address = profile_data.get("delivery_address")
            user.profile.save()

            # login user
            auth.login(request, user)
            token, created = Token.objects.get_or_create(user=user)
            user_serializer = UserSerializer(user)
            return Response({"token": token.key, "user": user_serializer.data})

        return Response({})


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
        return Response({"msg": "Wrong credintial"}, status=400)


class PaymentViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PaymentSerializer
    queryset = Payment.objects.all()
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


class PayViewSet(viewsets.ViewSet):
    """Handels all types of user payments"""

    permission_classes = [CanPay]

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
            user.profile.monthly_contribution = amount

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
            raise NotAcceptable(e.user_message)


class ContacUs(viewsets.ViewSet):
    @list_route(methods=["post"])
    def mail_us(self, request):
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
                "api-key": "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",
                "accept": "application/json",
                "content-type": "application/json",
            },
        )

        return Response({"details": "sent"})
