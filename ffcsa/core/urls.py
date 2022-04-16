from __future__ import unicode_literals
import json

from django.conf.urls import url
from django.conf.urls.i18n import i18n_patterns
from django.views.generic import TemplateView
from mezzanine.conf import settings
from mezzanine.core.views import page_not_found
from mezzanine.accounts.views import profile_update

from ffcsa.core import views
from ffcsa.core import dropsites


ACCOUNT_URL = getattr(settings, "ACCOUNT_URL", "/accounts/")
SIGNUP_URL = getattr(
    settings, "SIGNUP_URL", "/%s/signup/" % ACCOUNT_URL.strip("/")
)

_slash = "/" if settings.APPEND_SLASH else ""

urlpatterns = i18n_patterns(
    url("^$", views.home, name="home"),
    url("^shop%s$" % _slash, views.shop_home, name="shop_home"),
    url("^%s%s$" % (SIGNUP_URL.strip("/"), _slash), views.signup, name="mezzanine_signup"),
    url("^donate%s$" % _slash, views.donate, name="donate"),
    # TODO remove these for one-time orders
    url("^checkout%s$" % _slash, page_not_found, name="shop_checkout"),
    url("^checkout/complete%s$" % _slash, page_not_found, name="shop_complete"),
    url("^stripe%s$" % _slash, views.stripe_webhooks),
    url("^accounts/update%s$" % _slash, profile_update, kwargs={"extra_context": {"title": "Account Settings"}}),
    url(r'^country-autocomplete/$', views.ProductAutocomplete.as_view(), name='product-autocomplete'),
    url(r'^zip-check/(?P<zip>\d{5})$', views.home_delivery_check, name='home-delivery-zip-check'),
    url(r'^signrequest/$', views.SignRequest.as_view(), name='signrequest'),
    url(r'^signrequest-success/$', TemplateView.as_view(template_name='ffcsa_core/signrequest_success.html'),
        name='signrequest-success'),
    url(r'^signrequest-declined/$', TemplateView.as_view(template_name='ffcsa_core/signrequest_declined.html'),
        name='signrequest-declined'),

    # public pages
    url(r'^faq/$', TemplateView.as_view(template_name='pages/faq.html'), name='faq_page')

)
