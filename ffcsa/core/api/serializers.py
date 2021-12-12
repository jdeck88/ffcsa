from django.contrib.auth import get_user_model
from django.conf import settings
from googleapiclient import model
from rest_framework import serializers
from rest_framework.exceptions import NotAcceptable

from ffcsa.core.models import Profile, Payment, Address
User = get_user_model()


# Login Serializer
class LoginSerializer(serializers.Serializer):
    username = serializers.EmailField()
    password = serializers.CharField(min_length=6)

# Change password Serializer
class ChangePasswordSerializer(serializers.Serializer):
    cpassword = serializers.CharField(min_length=6)
    password = serializers.CharField(min_length=6)
    password2 = serializers.CharField(min_length=6)

# Address Serializer
class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        exclude = ('id', )

# Profile Serializer
class ProfileSerializer(serializers.ModelSerializer):
    delivery_address = serializers.SerializerMethodField()
    
    class Meta:
        model = Profile
        exclude = ('id', )
        read_only_fields = ('stripe_customer_id', 'stripe_subscription_id', 
            'payment_method', 'ach_status', 'discount_code', 'user', 'paid_signup_fee', 'can_order_dairy', 'google_person_id')

    def get_delivery_address(self, obj):
        return str(obj.delivery_address)

# Payment Serializer
class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = '__all__'


# User Serializer
class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'profile')


# NonMember Serializer
class NonMemberSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    amount = serializers.FloatField(min_value=settings.NON_MEMBERS_MIN_PURCHACE)
    stripeToken = serializers.CharField(required=False)


# OneTimePayment Serializer
class OneTimePaymentSerializer(serializers.Serializer):
    amount = serializers.FloatField(min_value=20)
    stripeToken = serializers.CharField(required=False)
    
    def validate(self, data):
        # Validate user has stripe_customer_id
        user = self.context['request'].user
        if not user.profile.stripe_customer_id:
            raise NotAcceptable('Could not find a valid customer id. Please contact the site administrator.')
        return data


# VerifyACHDeposits Serializer
class VerifyACHDepositsSerializer(serializers.Serializer):
    amount1 = serializers.FloatField()
    amount2 = serializers.FloatField()

    def validate(self, data):
        # Validate user has stripe_customer_id
        user = self.context['request'].user
        # if not user.profile.stripe_customer_id:
        #     raise NotAcceptable('Could not find a valid customer id. Please contact the site administrator.')
        return data


# Subscribe Serializer
class SubscribeSerializer(serializers.Serializer):
    amount = serializers.FloatField()
    stripeToken = serializers.CharField()
    paymentType = serializers.ChoiceField(choices=('CC', 'ACH'))

