from rest_framework import routers
from ffcsa.core.api.viewsets import *

router = routers.SimpleRouter()

router.register('login', LoginViewSet, base_name='login')
router.register('signup', SignupViewSet, base_name='signup')

router.register('resources', AppResources, base_name='resources')
router.register('users', UserViewSet, base_name='users')
router.register('payments', PaymentViewSet, base_name='payments')
router.register('pay', PayViewSet, base_name='pay')
router.register('contactus', ContacUs, base_name='contactus')
router.register('leadgen_pdf', LeadGenPDF, base_name='leadgen_pdf')
