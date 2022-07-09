from __future__ import unicode_literals

from django.contrib.messages import info
from django.contrib.auth import login as auth_login
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from mezzanine.conf import settings
from mezzanine.utils.email import send_mail_template

from .forms import ProfileForm


def signup(request, template="accounts/account_signup.html",
           extra_context=None):
    """
    invitation only signup form.
    """
    if not (request.GET.get('code') and request.GET.get('email')):
        raise Http404('You must have an invitation code to signup')

    form = ProfileForm(
        request.POST or None,
        initial={'code': request.GET.get('code'), 'email': request.GET.get('email')}
    )

    if request.method == "POST" and form.is_valid():
        new_user = form.save()
        info(request, _("Successfully signed up"))
        auth_login(request, new_user)

        c = {
            'user': "{} {}".format(new_user.first_name, new_user.last_name),
            'site_url': request.build_absolute_uri(reverse("home")),
            'user_url': request.build_absolute_uri(reverse("admin:ffcsa_core_user_change", args=(new_user.id,)))
        }
        send_mail_template(
            "New User Account %s" % settings.SITE_TITLE,
            "invites/send_new_user_email",
            settings.DEFAULT_FROM_EMAIL,
            settings.ACCOUNTS_APPROVAL_EMAILS,
            context=c,
            fail_silently=True,
        )

        return HttpResponseRedirect(reverse('payments'))

    context = {"form": form, "title": _("Sign up")}
    context.update(extra_context or {})
    return TemplateResponse(request, template, context)
