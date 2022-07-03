import datetime
import stripe
from django.utils import formats

from django.contrib.auth import get_user_model
from django.conf import settings
from googleapiclient import model
from rest_framework import serializers
from rest_framework.exceptions import NotAcceptable

from ffcsa.core.models import Profile, Payment, Address

User = get_user_model()


# Signup Serializer
class SignupProfileSerializer(serializers.Serializer):
    invite_code = serializers.CharField(required=False)  # ? not included in the model
    phone_number = serializers.CharField()
    phone_number_2 = serializers.CharField(required=False)
    num_adults = serializers.IntegerField()
    num_children = serializers.IntegerField(required=False)  # ? not included in the model
    drop_site = serializers.CharField(required=False)
    home_delivery = serializers.BooleanField(required=False)
    delivery_address = serializers.CharField(required=False)
    join_dairy_program = serializers.BooleanField(required=False)
    payment_agreement = serializers.BooleanField()
    pickup_agreement = serializers.BooleanField(required=False)  # ? not included in the model
    delivery_notes = serializers.CharField(required=False)
    communication_method = serializers.CharField(required=False)  # ? not included in the model
    best_time_to_reach = serializers.TimeField(required=False)  # ? not included in the model
    hear_about_us = serializers.CharField(required=False)  # ? not included in the mode


class SignupSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=6)
    password2 = serializers.CharField(min_length=6)


# Login Serializer
class LoginSerializer(serializers.Serializer):
    username = serializers.EmailField()
    password = serializers.CharField(min_length=6)


# Reset password Serializer
class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


# Change password Serializer
class ChangePasswordSerializer(serializers.Serializer):
    cpassword = serializers.CharField(min_length=6)
    password = serializers.CharField(min_length=6)
    password2 = serializers.CharField(min_length=6)


# Address Serializer
class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        exclude = ("id",)


# Profile Serializer
class ProfileSerializer(serializers.ModelSerializer):
    delivery_address = serializers.SerializerMethodField()
    next_payment_date = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        exclude = ("id", "user", "discount_code", "stripe_customer_id", "stripe_subscription_id", "google_person_id")

        read_only_fields = (
            "stripe_customer_id",
            "stripe_subscription_id",
            "payment_method",
            "ach_status",
            "discount_code",
            "user",
            "paid_signup_fee",
            "can_order_dairy",
            "google_person_id",
        )

    def get_delivery_address(self, obj):
        if obj.delivery_address:
            return str(obj.delivery_address)

        return ""

    def get_next_payment_date(self, obj):
        next_payment_date = None
        if obj.user.profile.stripe_subscription_id:
            subscription = stripe.Subscription.retrieve(obj.user.profile.stripe_subscription_id)
            next_payment_date = datetime.date.fromtimestamp(subscription.current_period_end + 1)
            next_payment_date = formats.date_format(next_payment_date, "D, F d")

        elif settings.DEBUG:
            next_payment_date = datetime.datetime.today() + datetime.timedelta(days=62)
            next_payment_date = formats.date_format(next_payment_date, "D, F d")

        return next_payment_date


# Payment Serializer
class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = "__all__"


# User Serializer
class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "profile")


# NonMember Serializer
class NonMemberSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    amount = serializers.FloatField(min_value=settings.NON_MEMBERS_MIN_PURCHACE)
    stripeToken = serializers.CharField(required=False)


class UpdatePaymentMethodSerializer(serializers.Serializer):
    paymentType = serializers.ChoiceField(choices=("CC", "ACH"))
    stripeToken = serializers.CharField(required=False)


class UpdatePaymentAmountSerializer(serializers.Serializer):
    amount = serializers.FloatField(min_value=172)


# OneTimePayment Serializer
class OneTimePaymentSerializer(serializers.Serializer):
    amount = serializers.FloatField(min_value=20)
    stripeToken = serializers.CharField(required=False)

    def validate(self, data):
        # Validate user has stripe_customer_id
        user = self.context["request"].user
        if not user.profile.stripe_customer_id:
            raise NotAcceptable("Could not find a valid customer id. Please contact the site administrator.")
        return data


# VerifyACHDeposits Serializer
class VerifyACHDepositsSerializer(serializers.Serializer):
    amount1 = serializers.FloatField()
    amount2 = serializers.FloatField()

    def validate(self, data):
        # Validate user has stripe_customer_id
        user = self.context["request"].user
        # if not user.profile.stripe_customer_id:
        #     raise NotAcceptable('Could not find a valid customer id. Please contact the site administrator.')
        return data


# Subscribe Serializer
class SubscribeSerializer(serializers.Serializer):
    amount = serializers.FloatField()
    stripeToken = serializers.CharField()
    paymentType = serializers.ChoiceField(choices=("CC", "ACH"))


# ContactUs Serializer
class ContactUsSerializer(serializers.Serializer):
    target = serializers.CharField()
    name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField(allow_blank=True)
    message = serializers.CharField()


# Lead Gen PDF
class LeadGenPDFSerializer(serializers.Serializer):
    first_name = serializers.CharField(allow_blank=True, required=False)
    last_name = serializers.CharField(allow_blank=True, required=False)
    email = serializers.EmailField()


# Donate Serializer
class DonateSerializer(serializers.Serializer):
    amount = serializers.FloatField()
