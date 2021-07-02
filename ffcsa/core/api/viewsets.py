import datetime
import stripe
from django.contrib import auth
from django.contrib.auth import get_user_model
from rest_framework import mixins, views
from rest_framework import viewsets
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import detail_route, list_route
from rest_framework.exceptions import NotAcceptable
from django.shortcuts import get_object_or_404

from ffcsa.core import sendinblue, signrequest
from ffcsa.core.api.permissions import IsOwner
from ffcsa.core.api.serializers import *
from ffcsa.core.models import Payment
from ffcsa.core.subscriptions import *

User = get_user_model()



class UserViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.all()
    permission_classes = [IsAuthenticated, IsOwner]


    def update(self, request, *args, **kwargs):
        user = get_object_or_404(User, pk=kwargs['pk'])
        profile_data = request.data.pop('profile')

        # save user data
        serializer = UserSerializer(user, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # save user profile data
        serializer = ProfileSerializer(user.profile, data=profile_data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response({})


class LoginViewSet(viewsets.ViewSet):
    ''' Authenticate user and return user with token '''
    serializer_class = LoginSerializer

    def create(self, request):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        user = auth.authenticate(**serializer.data)
        if user:
            auth.login(request, user)
            token, created = Token.objects.get_or_create(user=user)
            user_serializer = UserSerializer(user)
            return Response({'token': token.key, 'user': user_serializer.data})
        return Response({'msg': 'Wrong credintial'}, status=400)


class PaymentViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PaymentSerializer
    queryset = Payment.objects.all()
    permission_classes = [IsAuthenticated]

    @list_route(methods=['get'])
    def only_payments(self, request):
        queryset = self.queryset.filter(user=request.user, is_credit=False)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @list_route(methods=['get'])
    def only_credits(self, request):
        queryset = self.queryset.filter(user=request.user, is_credit=True)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class PayViewSet(viewsets.ViewSet):
    ''' Handels all types of user payments '''
    permission_classes = [IsAuthenticated]

    # >>>>>> make_payment
    @list_route(methods=['post'])
    def one_time_payment(self, request):
        ''' Make ont time payment using stripe Charge '''
        serializer = OneTimePaymentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        try:
            card = None
            if serializer.data.get('stripeToken', None):
                # create customer card
                customer = stripe.Customer.retrieve(request.user.profile.stripe_customer_id)
                card = customer.sources.create(source=serializer.data.get('stripeToken'))
            
            res = stripe.Charge.create(
                amount=(int(serializer.data.get('amount') * 100)),  # in cents
                currency='usd',
                description=PAYMENT_DESCRIPTION,
                customer=request.user.profile.stripe_customer_id,
                source=card.id if card else None,
                statement_descriptor=PAYMENT_DESCRIPTION,
            )

            # Payment will be created when the charge is successful
            return Response({'detail': 'Your payment is pending'})

        except Exception as e:
            raise NotAcceptable(e.json_body.get('error').get('message', 'Something went wrong!'))

    # >>>>>> verify_ach
    @list_route(methods=['post'])
    def verify_ach_deposits(self, request):
        serializer = VerifyACHDepositsSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        amount1, amount2 = serializer.data.values()
        customer = stripe.Customer.retrieve(user.profile.stripe_customer_id)
        bank_account = customer.sources.retrieve(customer.default_source)

        try:
            bank_account.verify(amounts=[int(amount1), int(amount2)])
            user.profile.ach_status = 'VERIFIED'
            user.profile.save()

            # we can create the subscription right now
            if not user.profile.stripe_subscription_id:
                create_stripe_subscription(user)
                if not Payment.objects.filter(user=user).exists():
                    return Response({
                        'detail': 'Your account has been verified and your first payment is processing. '
                                  'When your payment has been received, you will receive an email letting '
                                  'you know when your first ordering and pickup dates are. If you do not '
                                  'see this email in the next 5 - 7 business days, please check your spam'
                    })
                else:
                    subscription = stripe.Subscription.retrieve(user.profile.stripe_subscription_id)
                    next_payment_date = datetime.date.fromtimestamp(subscription.current_period_end + 1)
                    next_payment_date = formats.date_format(next_payment_date, "D, F d")
                    return Response({
                        'detail': 'Congratulations, your account has been verified and your first payment is processing. '
                                  'You will be seeing this amount show up in your member store account in 5 - 7 business '
                                  'days. Your next scheduled payment will be ' + next_payment_date
                    })
            else:
                return Response({'detail': 'Your account has been verified.'})
        
        except Exception as e:
            raise NotAcceptable(e)

    # >>>>>> payments_subscribe
    @list_route(methods=['post'])
    def subscribe(self, request):
        serializer = SubscribeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        amount, stripeToken, paymentType = serializer.data.values()

        if user.profile.join_dairy_program and not user.profile.paid_signup_fee:
            raise NotAcceptable('You must acknowledge the 1 time Raw Dairy program fee')

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

            if paymentType == 'ACH':
                user.profile.ach_status = 'VERIFIED' if customer.sources.data[0].status == 'verified' else 'NEW'
                user.profile.save()
                return Response({
                    'detail': 'Your subscription has been created. You will need to verify your bank account before your first payment is made.'
                })
            elif paymentType == 'CC':
                # we can create the subscription right now
                create_stripe_subscription(user)
                return Response({
                    'detail': 'Your subscription has been created and your first payment is pending. You should see the payment credited to your account within the next few minutes'
                })

        except Exception as e:
            raise NotAcceptable(e.json_body.get('error').get('message', 'Something went wrong!'))
        

