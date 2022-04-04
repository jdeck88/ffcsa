from __future__ import unicode_literals

from django.conf.urls import include, url
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.views.i18n import set_language
from django.views.generic import TemplateView
from mezzanine.conf import settings
from mezzanine.accounts.urls import PASSWORD_RESET_VERIFY_URL, _verify_pattern, _slash

import ffcsa.core.views as ffcsa_core
import ffcsa.shop.views as shop_ciews

# API router
from rest_framework import routers
from ffcsa.core.api.urls import router as core_router
from ffcsa.shop.api.urls import router as shop_router

router = routers.SimpleRouter()
router.registry.extend(core_router.registry)
router.registry.extend(shop_router.registry)


admin.autodiscover()

# Add the urlpatterns for any custom Django applications here.
# You can also change the ``home`` view to add your own functionality
# to the project's homepage.

urlpatterns = i18n_patterns(
    url(r'^admin/', include("ffcsa.core.admin_urls")),
    # Change the admin prefix here to use an alternate URL for the
    # admin interface, which would be marginally more secure.
    url("^admin/", include(admin.site.urls)),
)

if settings.USE_MODELTRANSLATION:
    urlpatterns += [
        url('^i18n/$', set_language, name='set_language'),
    ]

urlpatterns += [

    # ffcsa-core
    url("^", include("ffcsa.core.urls")),

    # ffcsainvites URLs
    # url("^", include("ffcsa.invites.urls")),

    # Shop URLs.
    url("^", include("ffcsa.shop.urls")),

    # api endpoint
    url("^api/", include(router.urls)),

    url("^account/orders/$", shop_ciews.order_history, name="shop_order_history"),
    url("^account/payments/$", ffcsa_core.payments, name="payments"),
    url("^account/payments/subscribe$", ffcsa_core.payments_subscribe, name="payments_subscribe"),
    url("^account/payments/verify$", ffcsa_core.verify_ach, name="payments_verify"),
    url("^account/payments/update$", ffcsa_core.payments_update, name="payments_update"),
    url("^account/payments/update/amount$", ffcsa_core.payments_update_amount, name="payments_update_amount"),
    url("^account/payments/new$", ffcsa_core.make_payment, name="make_payment"),
    url("^account/dairy/program/$", ffcsa_core.dairy_program, name="dairy_program"),

    url(
        r"^{}{}{}$".format(
            PASSWORD_RESET_VERIFY_URL.strip("/"), _verify_pattern, _slash
        ),
        ffcsa_core.password_reset_verify,
        name="password_reset_verify",
    ),

    # We don't want to presume how your homepage works, so here are a
    # few patterns you can use to set it up.

    # HOMEPAGE AS STATIC TEMPLATE
    # ---------------------------
    # This pattern simply loads the index.html template. It isn't
    # commented out like the others, so it's the default. You only need
    # one homepage pattern, so if you use a different one, comment this
    # one out.

    # url("^$", direct_to_template, {"template": "index.html"}, name="home"),

    # HOMEPAGE AS AN EDITABLE PAGE IN THE PAGE TREE
    # ---------------------------------------------
    # This pattern gives us a normal ``Page`` object, so that your
    # homepage can be managed via the page tree in the admin. If you
    # use this pattern, you'll need to create a page in the page tree,
    # and specify its URL (in the Meta Data section) as "/", which
    # is the value used below in the ``{"slug": "/"}`` part.
    # Also note that the normal rule of adding a custom
    # template per page with the template name using the page's slug
    # doesn't apply here, since we can't have a template called
    # "/.html" - so for this case, the template "pages/index.html"
    # should be used if you want to customize the homepage's template.
    # NOTE: Don't forget to import the view function too!

    # url("^$", mezzanine.pages.views.page, {"slug": "/"}, name="home"),

    # HOMEPAGE FOR A BLOG-ONLY SITE
    # -----------------------------
    # This pattern points the homepage to the blog post listing page,
    # and is useful for sites that are primarily blogs. If you use this
    # pattern, you'll also need to set BLOG_SLUG = "" in your
    # ``settings.py`` module, and delete the blog page object from the
    # page tree in the admin if it was installed.
    # NOTE: Don't forget to import the view function too!

    # url("^$", mezzanine.blog.views.blog_post_list, name="home"),

    # MEZZANINE'S URLS
    # ----------------
    # ADD YOUR OWN URLPATTERNS *ABOVE* THE LINE BELOW.
    # ``mezzanine.urls`` INCLUDES A *CATCH ALL* PATTERN
    # FOR PAGES, SO URLPATTERNS ADDED BELOW ``mezzanine.urls``
    # WILL NEVER BE MATCHED!

    # If you'd like more granular control over the patterns in
    # ``mezzanine.urls``, go right ahead and take the parts you want
    # from it, and use them directly below instead of using
    # ``mezzanine.urls``.
    url("^", include("mezzanine.urls")),

    # MOUNTING MEZZANINE UNDER A PREFIX
    # ---------------------------------
    # You can also mount all of Mezzanine's urlpatterns under a
    # URL prefix if desired. When doing this, you need to define the
    # ``SITE_PREFIX`` setting, which will contain the prefix. Eg:
    # SITE_PREFIX = "my/site/prefix"
    # For convenience, and to avoid repeating the prefix, use the
    # commented out pattern below (commenting out the one above of course)
    # which will make use of the ``SITE_PREFIX`` setting. Make sure to
    # add the import ``from django.conf import settings`` to the top
    # of this file as well.
    # Note that for any of the various homepage patterns above, you'll
    # need to use the ``SITE_PREFIX`` setting as well.

    # url("^%s/" % settings.SITE_PREFIX, include("mezzanine.urls"))

]

# Adds ``STATIC_URL`` to the context of error pages, so that error
# pages can use JS, CSS and images.
handler404 = "mezzanine.core.views.page_not_found"
handler500 = "mezzanine.core.views.server_error"
