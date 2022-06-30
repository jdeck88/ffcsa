from __future__ import unicode_literals

from django.core import urlresolvers
from mezzanine.conf import settings

from mezzanine.pages.middleware import PageMiddleware
from mezzanine.utils.deprecation import MiddlewareMixin

from ffcsa.shop.models import Cart


class ShopMiddleware(MiddlewareMixin):
    """
    Adds cart  attributes to the current request.
    """

    def process_request(self, request):
        request.cart = Cart.objects.from_request(request)
        request.STRIPE_API_KEY = settings.STRIPE_API_KEY
        request.NON_MEMBERS_MIN_PURCHACE = settings.NON_MEMBERS_MIN_PURCHACE


class MultiurlPageMiddleware(PageMiddleware):
    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        Wraps mezzanine PageMiddleware, providing support for multiurl
        PageMiddleware will detect if the view_func != page_view and attempt to 
        call the view_func (in order to allow calling other apps pages). It then
        catches 404s and renders the page template. When using multiurl for the page
        url, the view_func is a multiurl function.
        """
        if hasattr(view_func, 'multi_resolver_match'):
            for match in view_func.multi_resolver_match.matches:
                try:
                    # should we pass view_args & view_kwargs???
                    return super(MultiurlPageMiddleware, self).process_view(request, match.func, match.args,
                                                                            match.kwargs)
                except view_func.multi_resolver_match.exceptions:
                    continue

            raise urlresolvers.Resolver404(
                {'tried': view_func.multi_resolver_match.patterns_matched, 'path': view_func.multi_resolver_match.path})

        return super(MultiurlPageMiddleware, self).process_view(request, view_func, view_args, view_kwargs)
