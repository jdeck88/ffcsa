from __future__ import unicode_literals

from copy import deepcopy

import stripe
from dal import autocomplete
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import ImageField
from django.http import HttpResponseRedirect
from django.urls import reverse
from mezzanine.accounts import admin as accounts_base
from mezzanine.conf import settings
from mezzanine.core.admin import SitePermissionInline
from mezzanine.generic.models import ThreadedComment
from mezzanine.pages.admin import PageAdmin

from ffcsa.shop.models import Sale
from ffcsa.shop.forms import OptionalContentAdminForm, ImageWidget
from ffcsa.core.subscriptions import update_stripe_subscription

from .models import Payment, Recipe, RecipeProduct

User = get_user_model()

accounts_base.ProfileInline.readonly_fields = ['google_person_id']
accounts_base.ProfileInline.fieldsets = (
    (None, {'fields': ('phone_number', 'phone_number_2', 'notes', 'num_adults', 'invoice_notes')}),
    ('Payments', {'fields': (
        'monthly_contribution', 'discount_code', 'paid_signup_fee', 'payment_method', 'ach_status',
        'stripe_subscription_id', 'stripe_customer_id')}),
    ('Preferences', {'fields': ('home_delivery', 'delivery_address', 'delivery_notes', 'drop_site', 'plastic_bags',
                                'allow_substitutions', 'weekly_emails')}),
    ('Other', {'fields': ('start_date', 'join_dairy_program', 'can_order_dairy',
                          'signed_membership_agreement', 'non_subscribing_member')}),

)

user_fieldsets = deepcopy(accounts_base.UserProfileAdmin.fieldsets)
user_fieldsets[2][1]['classes'] = ('collapse', 'collapse-closed')
SitePermissionInline.classes = ('collapse', 'collapse-closed')

user_list_filter = list(deepcopy(accounts_base.UserProfileAdmin.list_filter))
user_list_filter.append('profile__drop_site')
user_list_filter.append('profile__home_delivery')
user_list_filter.append('profile__join_dairy_program')


def formfield_for_dbfield(self, db_field, request, **kwargs):
    if db_field.name == "delivery_address":
        return db_field.formfield(**kwargs)

    return super(accounts_base.ProfileInline, self).formfield_for_dbfield(db_field, request, **kwargs)


class ProfileAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['delivery_address'].widget.attrs['class'] = 'vTextField'
        if self.instance:
            self.initial['delivery_address'] = str(self.instance.delivery_address) if self.instance.home_delivery else ''


accounts_base.ProfileInline.formfield_for_dbfield = formfield_for_dbfield
accounts_base.ProfileInline.form = ProfileAdminForm


class UserProfileAdmin(accounts_base.UserProfileAdmin):
    fieldsets = user_fieldsets
    list_filter = tuple(user_list_filter)

    def save_model(self, request, obj, form, change):
        """
        Update stripe subscription if needed
        """
        user = User.objects.get(id=obj.id) if change else None
        if change \
                and user.profile.monthly_contribution != obj.profile.monthly_contribution \
                and obj.profile.stripe_subscription_id:
            update_stripe_subscription(obj)
        if change and obj.profile.non_subscribing_member:
            if user.profile.stripe_subscription_id:
                # TODO: this is not a very good UX
                self.message_user(request, 'Non-subscribing members can not have an existing subscription',
                                  messages.ERROR)
                raise ValidationError(
                    'Non-subscribing members can not have an existing subscription')
            # create stripe user if not already existing
            if not obj.profile.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=user.email,
                    description=user.get_full_name()
                )
                obj.profile.stripe_customer_id = customer.id

            # only accepts CC payments
            obj.profile.payment_method = 'CC'
            obj.profile.ach_status = None

        super(UserProfileAdmin, self).save_model(request, obj, form, change)


class PaymentAdmin(admin.ModelAdmin):
    date_hierarchy = 'date'
    list_display = ('user', 'date', 'pending', 'amount', 'is_credit')
    list_filter = ("user", "date", 'is_credit')
    search_fields = ["user__first_name", "user__last_name", "user__username"]

    actions = ['bulk_edit']

    def bulk_edit(self, request, queryset):
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        return HttpResponseRedirect(reverse('admin_bulk_payments') + "?ids=%s" % ",".join(selected))

    bulk_edit.short_description = "Edit selected payments"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(
                is_active=True).order_by('last_name')
        return super(PaymentAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)


recipe_fieldsets = deepcopy(PageAdmin.fieldsets)
recipe_fieldsets[0][1]["fields"][3:3] = ["content"]
# for some reason the trailing , in the classes tuple causes django to throw the error: (admin.E012) There are duplicate field(s) in 'fieldsets[0][1]'.
# so we remove it here
recipe_fieldsets[1][1]['classes'] = ('collapse', 'collapse-closed')
if settings.SHOP_CATEGORY_USE_FEATURED_IMAGE:
    recipe_fieldsets[0][1]["fields"].insert(3, "featured_image")


class ProductForm(forms.ModelForm):
    class Meta:
        model = RecipeProduct
        fields = ('__all__')
        widgets = {
            'product': autocomplete.ModelSelect2(url='product-autocomplete')
        }


class RecipeProductInlineAdmin(admin.TabularInline):
    model = Recipe.products.through
    form = ProductForm


class RecipeAdmin(PageAdmin):
    form = OptionalContentAdminForm
    fieldsets = recipe_fieldsets
    formfield_overrides = {ImageField: {"widget": ImageWidget}}
    inlines = (RecipeProductInlineAdmin,)


admin.site.unregister(User)
admin.site.register(User, UserProfileAdmin)

admin.site.register(Payment, PaymentAdmin)
admin.site.register(Recipe, RecipeAdmin)

# TODO remove all unnecessary admin menus
admin.site.unregister(ThreadedComment)
admin.site.unregister(Sale)
