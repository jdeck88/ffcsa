import datetime

from django import forms
from django.core import validators
from django.db import transaction, connection
from django.urls import reverse
from mezzanine.accounts import forms as accounts_forms
from mezzanine.conf import settings
from mezzanine.core.request import current_request
from mezzanine.utils.email import send_mail_template

from ffcsa.core import sendinblue, dropsites
from ffcsa.core.dropsites import get_full_drop_locations
from ffcsa.core.google import update_contact as update_google_contact
from ffcsa.core.models import DropSiteInfo, PHONE_REGEX
from ffcsa.core.utils import give_emoji_free_text
from ffcsa.shop.models import OrderItem
from ffcsa.shop.orders import get_order_period_for_user
from ffcsa.shop.utils import clear_shipping, set_home_delivery, recalculate_remaining_budget


class CartDinnerForm(forms.Form):
    attending_dinner = forms.IntegerField(
        min_value=0, label="Attending dinner at the farm?", required=False)

    def __init__(self, request, data=None, initial=None, **kwargs):
        self._cart = request.cart

        if not data:
            data = {'attending_dinner': self._cart.attending_dinner}

        super(CartDinnerForm, self).__init__(
            data=data, initial=initial, **kwargs)

    def save(self):
        if 'attending_dinner' in self.changed_data:
            self._cart.attending_dinner = self.cleaned_data['attending_dinner']
            self._cart.save()


# monkey patch the cart item form to use custom clean_quantity method
# TODO update sku for CartItem when product sku changes
# original_cart_item_clean_quantity = deepcopy(CartItemForm.clean_quantity)


# def cart_item_clean_quantity(self):
#     # if the sku was changed while a product was in the cart, an exception will be thrown while trying to update the
#     # inventory. Since we don't use inventory much we want to catch that exception and ignore the error, acknowledging
#     # that we may have more in stock then inventory mentions
#     try:
#         variation = ProductVariation.objects.get(sku=self.instance.sku)
#         if not variation.product.available:
#             # setting the following will let django delete the item
#             self.fields['DELETE'].disabled = True
#             self.fields['DELETE'].initial = True
#             self.initial['DELETE'] = True
#             self.add_error(None,
#                            _("'%s' was removed from your cart as it is no longer available." % variation.product.title))
#             return 0
#         return original_cart_item_clean_quantity(self)
#     except ProductVariation.DoesNotExist:
#         return 0


# CartItemForm.clean_quantity = cart_item_clean_quantity
def sanitize_phone_number(num):
    if not num or not num.strip():
        return num

    num = num.replace('(', '').replace(')', '').replace(
        ' ', '').replace('-', '').strip()

    if len(num) > 10 and num.startswith('1'):
        return '1-' + num[1:4] + '-' + num[4:7] + '-' + num[7:]

    return num[:3] + '-' + num[3:6] + '-' + num[6:]


class DropsiteSelectWidget(forms.Select):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._full_locations = get_full_drop_locations()

    def create_option(self, *args, **kwargs):
        opt = super().create_option(*args, **kwargs)
        if opt['value'] in self._full_locations:
            opt['attrs']['disabled'] = True
            opt['label'] = '(Full) - ' + opt['label']
        if opt['value'] in dropsites.PRIVATE_DROPSITES:
            opt['attrs']['hidden'] = True
        return opt


class ProfileForm(accounts_forms.ProfileForm):
    # NOTE: Any fields on the profile that we don't include in this form need to be added to settings.py ACCOUNTS_PROFILE_FORM_EXCLUDE_FIELDS
    username = None

    class Media:
        js = ('js/forms/profile/profile_form.js',)

    def __init__(self, *args, **kwargs):
        super(ProfileForm, self).__init__(*args, **kwargs)

        del self.fields['first_name'].widget.attrs['autofocus']

        # for some reason, the Profile model validators are not copied over to the form, so we add them here
        self.fields['num_adults'].validators.append(validators.MinValueValidator(1))

        # self.fields['delivery_address'].required = False
        self.fields['delivery_address'].widget.attrs['readonly'] = ''
        self.fields['delivery_address'].widget.attrs['class'] = 'mb-3 mr-4'
        self.fields['delivery_notes'].widget.attrs = {'rows': 3, 'cols': 40,
                                                      'placeholder': 'Any special notes to give to our delivery driver regarding your delivery/location.'}

        self.fields['phone_number'].widget.attrs['placeholder'] = '123-456-7890'
        self.fields['phone_number_2'].widget.attrs['placeholder'] = '123-456-7890'
        # self.fields['drop_site'] = forms.ChoiceField(widget=DropsiteSelectWidget(),
        #                                              choices=dropsites.DROPSITE_CHOICES, label="Drop Site Location",
        #                                              help_text="Our Portland dropsites are currently full. <a target='_blank' href='https://26403a96.sibforms.com/serve/MUIEAEe-Lhh9Ij9OVpUCDzojW-Mdekxfy3xZjo7tka8o97OAN5FCESzSdtZnYvRkQkahzra5SB0It2X_txOn8Osv64fHf6t3Cv15W_S8yXTczZbBQfQ7Z_voZO4w2Q48UtGXYMgQaelSC0ni3_GivthfTK9FvMchpVPz-q7Y2JscpW2VjQjQSGgfNoJ56dxcF6ASqRwLc5Qkpa2S'>Join our waitlist</a> to be notified when a spot opens up.")

        if self.instance.id is not None:
            self.initial['drop_site'] = self.instance.profile.drop_site

        if self._signup:
            self.fields['pickup_agreement'] = forms.BooleanField(
                label="I agree to bring my own bags and coolers as needed to pick up my product. The containers "
                      "that the product arrives in stay at the dropsite. I intend to maintain my membership with the FFCSA "
                      "for 6 months, with a minimum payment of $172 per month.")

            # self.fields[''] = forms.FileField(label="Signed Member Product Liability Agreement",
            # self.fields['invite_code'] = forms.CharField(label="Invite Code (Portland dropsites only)",
            #                                              required=False)
            self.fields['best_time_to_reach'] = forms.CharField(label="What is the best time to reach you?",
                                                                required=True)
            self.fields['communication_method'] = forms.ChoiceField(
                label="What is your preferred method of communication?", required=True,
                choices=(("Email", "Email"), ("Phone", "Phone"), ("Text", "Text")))
            self.fields['num_children'] = forms.IntegerField(label="How many children are in your family?",
                                                             required=True, min_value=0)
            self.fields['hear_about_us'] = forms.CharField(label="How did you hear about us?", required=True,
                                                           widget=forms.Textarea(attrs={'rows': 3}))
            # self.fields['payment_agreement'].required = True
            self.initial['num_adults'] = None
        else:
            # All fields (only checkboxes?) must be rendered in the form unless they are included in settings.ACCOUNTS_PROFILE_FORM_EXCLUDE_FIELDS
            # Otherwise they will be reset/overridden
            self.fields['payment_agreement'].widget = forms.HiddenInput()
            self.fields['join_dairy_program'].widget = forms.HiddenInput()
            self.fields['num_adults'].widget = forms.HiddenInput()
            self.fields['drop_site'].help_text = None

        if not settings.HOME_DELIVERY_ENABLED:
            del self.fields['home_delivery']

    def get_profile_fields_form(self):
        return ProfileFieldsForm

    def clean_phone_number(self):
        num = self.cleaned_data['phone_number']
        num = sanitize_phone_number(num)
        PHONE_REGEX(num)
        return num

    def clean_phone_number_2(self):
        num = self.cleaned_data['phone_number_2']
        num = sanitize_phone_number(num)
        if num:
            PHONE_REGEX(num)
        return num

    def clean(self):
        cleaned_data = super().clean()

        home_delivery = cleaned_data.get('home_delivery', False)
        if home_delivery:
            if not cleaned_data['delivery_address']:
                self.add_error('delivery_address', 'Please provide an address for your delivery.')
        elif not cleaned_data.get('drop_site', False):
            self.add_error('drop_site', 'Please either choose a drop_site or home delivery.')

        if not home_delivery:
            cleaned_data['delivery_address'] = None

            if self._signup and cleaned_data.get(
                    'drop_site') in settings.INVITE_ONLY_PORTLAND_MARKETS and cleaned_data.get('invite_code',
                                                                                               None) != settings.INVITE_CODE:
                self.add_error('invite_code', '')
                self.add_error(None,
                               'Due to limited capacity, Portland dropsites are invite only. Either enter your invite code below or join our waitlist to be notified when a spot opens up.')

        return cleaned_data

    def save(self, *args, **kwargs):
        old_order_period_start = get_order_period_for_user(self.instance) if hasattr(self.instance,
                                                                                     'profile') else (None, None)

        with transaction.atomic():
            user = super(ProfileForm, self).save(*args, **kwargs)

            drop_site = self.cleaned_data['drop_site']
            user.profile.drop_site = drop_site
            sib_template_name = drop_site

            if self._signup:
                user.profile.notes = "<b>Best time to reach:</b>  {}<br/>" \
                                     "<b>Preferred communication method:</b>  {}<br/>" \
                                     "<b>Adults in family:</b>  {}<br/>" \
                                     "<b>Children in family:</b>  {}<br/>" \
                                     "<b>How did you hear about us:</b>  {}<br/>" \
                    .format(self.cleaned_data['best_time_to_reach'],
                            self.cleaned_data['communication_method'],
                            self.cleaned_data['num_adults'],
                            self.cleaned_data['num_children'],
                            self.cleaned_data['hear_about_us'])

                # defaults
                user.profile.allow_substitutions = True
                user.profile.weekly_emails = True
                user.profile.plastic_bags = False

                sib_template_name = 'Home Delivery' if user.profile.home_delivery else drop_site

                sendinblue.update_or_add_user(user, sendinblue.NEW_USER_LISTS, sendinblue.NEW_USER_LISTS_TO_REMOVE)

            user.profile.save()

        request = current_request()
        if not self._signup:
            # clear cart if order period changed
            if "home_delivery" in self.changed_data or "delivery_address" in self.changed_data or "drop_site" in self.changed_data:
                new_order_period_start = get_order_period_for_user(user)
                if old_order_period_start != new_order_period_start:
                    request.cart.clear()
                    recalculate_remaining_budget(request)

            # we can't set this on signup b/c the cart.user_id has not been set yet
            if "home_delivery" in self.changed_data or "delivery_address" in self.changed_data:
                if user.profile.home_delivery:
                    set_home_delivery(request)
                    sib_template_name = 'Home Delivery'
                else:
                    clear_shipping(request)
                    sib_template_name = drop_site

                recalculate_remaining_budget(request)


            elif 'drop_site' in self.changed_data:
                sib_template_name = drop_site

            update_google_contact(user)

            # The following NOPs if settings.SENDINBLUE_ENABLED == False
            weekly_email_lists = ['WEEKLY_NEWSLETTER']
            lists_to_add = weekly_email_lists if user.profile.weekly_emails else None
            lists_to_remove = weekly_email_lists if not user.profile.weekly_emails else None
            sendinblue.update_or_add_user(user, lists_to_add, lists_to_remove)

        # Send drop site information (or home delivery instructions)
        if settings.SENDINBLUE_ENABLED and \
                (self._signup or
                 'drop_site' in self.changed_data or
                 'home_delivery' in self.changed_data or 'delivery_address' in self.changed_data):

            user_dropsite_info_set = user.profile.dropsiteinfo_set.all()
            user_dropsite_info = list(user_dropsite_info_set.filter(drop_site_template_name=sib_template_name))
            params = {'FIRSTNAME': user.first_name}

            # User has not received the notification before
            if len(user_dropsite_info) == 0:
                date_last_modified = sendinblue.send_transactional_email(sib_template_name, self.cleaned_data['email'],
                                                                         params)

                # If the email is successfully sent add an appropriate DropSiteInfo to the user
                if date_last_modified is not False:
                    _dropsite_info_obj = DropSiteInfo.objects.create(profile=user.profile,
                                                                     drop_site_template_name=sib_template_name,
                                                                     last_version_received=date_last_modified)
                    _dropsite_info_obj.save()

            # Check if user has received the latest version of the notification message
            else:
                date_last_modified = sendinblue.get_template_last_modified_date(sib_template_name)

                user_dropsite_entry = user_dropsite_info[0]
                if user_dropsite_entry.last_version_received != date_last_modified:
                    email_result = sendinblue.send_transactional_email(sib_template_name, self.cleaned_data['email'],
                                                                       params)

                    # Don't update entry if email fails to send
                    if email_result is not False:
                        user_dropsite_entry.last_version_received = email_result
                        user_dropsite_entry.save()

            user.profile.save()

        return user


class ProfileFieldsForm(accounts_forms.ProfileFieldsForm):

    def clean_delivery_notes(self):
        return give_emoji_free_text(self.cleaned_data['delivery_notes'])

    def clean_phone_number(self):
        num = self.cleaned_data['phone_number']
        return sanitize_phone_number(num)

    def clean_phone_number_2(self):
        num = self.cleaned_data['phone_number_2']
        return sanitize_phone_number(num)


class BasePaymentFormSet(forms.BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        if 'request' in kwargs:
            self.request = kwargs.pop('request')

        super(BasePaymentFormSet, self).__init__(*args, **kwargs)

    def add_fields(self, form, index):
        super(BasePaymentFormSet, self).add_fields(form, index)
        form.fields['is_credit'].initial = True
        form.fields['notify'] = forms.BooleanField(
            label="Notify User", initial=True, required=False)

    def save(self, commit=True):
        super(BasePaymentFormSet, self).save(commit)

        for d in self.cleaned_data:
            if d and d['notify']:
                send_mail_template(
                    "FFCSA Credit",
                    "ffcsa_core/applied_credit_email",
                    settings.DEFAULT_FROM_EMAIL,
                    d['user'].email,
                    fail_silently=True,
                    context={
                        'first_name': d['user'].first_name,
                        'amount': d['amount'],
                        'notes': d['notes'],
                        'payments_url': self.request.build_absolute_uri("/accounts/update/?section=payment") if self.request else None
                    }
                )


class CreditOrderedProductForm(forms.Form):
    date = forms.ChoiceField(help_text='Only order dates in the last 30 days are shown.')
    products = forms.MultipleChoiceField(help_text='Only products ordered in the last 30 days are shown.')
    notify = forms.BooleanField(required=False, label='Notify Members that a credit was issued?', initial=True)
    msg = forms.CharField(label='Message to include in the notification.', widget=forms.Textarea(attrs={'rows': 3}),
                          required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        thirty_days_ago = datetime.date.today() - datetime.timedelta(days=30)

        with connection.cursor() as cursor:
            cursor.execute('select distinct(date(time)) as date from shop_order where time >= %s', [thirty_days_ago])
            self.fields['date'].choices = [(o[0], o[0]) for o in cursor]

        self.fields['products'].choices = [(i['description'], i['description']) for i in
                                           OrderItem.objects.filter(order__time__gt=thirty_days_ago)
                                               .values('description').distinct().order_by(
                                               'description')
                                           ]
