from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import NotAcceptable

from ffcsa.core.models import Profile, Payment
User = get_user_model()


# Login Serializer
class LoginSerializer(serializers.Serializer):
    username = serializers.EmailField()
    password = serializers.CharField(min_length=6)


# Profile Serializer
class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ('phone_number', 'phone_number_2')


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


# OneTimePayment Serializer
class OneTimePaymentSerializer(serializers.Serializer):
    amount = serializers.FloatField(min_value=20)
    stripeToken = serializers.CharField(required=False)
    
    def validate(self, data):
        # Validate user has stripe_customer_id
        user = self.context['request'].user
        # todo - uncomment below line
        # if not user.profile.stripe_customer_id:
        #     raise NotAcceptable('Could not find a valid customer id. Please contact the site administrator.')
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

