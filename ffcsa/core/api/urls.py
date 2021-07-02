from rest_framework import routers
from ffcsa.core.api.viewsets import *

router = routers.SimpleRouter()

router.register('login', LoginViewSet, base_name='login')

router.register('users', UserViewSet, base_name='users')
router.register('payments', PaymentViewSet, base_name='payments')
router.register('pay', PayViewSet, base_name='pay')
