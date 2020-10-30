import datetime
import json

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import validators
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.fields.related_descriptors import ForwardManyToOneDescriptor
from mezzanine.core.fields import FileField, RichTextField
from mezzanine.core.models import RichText
from mezzanine.pages.models import Page
from mezzanine.utils.models import upload_to

from ffcsa.shop.fields import MoneyField
from ffcsa.core.managers import PaymentManager

User = get_user_model()


###################
#  User
###################


def patched_str_(self):
    if self.last_name and self.first_name:
        return "{}, {}".format(self.last_name, self.first_name)

    return self.get_username()


User.__str__ = patched_str_


class Address(models.Model):
    street = models.CharField(max_length=165)
    city = models.CharField(max_length=165)
    state = models.CharField(max_length=165)
    zip = models.CharField(max_length=10)
    country = models.CharField(max_length=165)

    class Meta:
        indexes = [
            models.Index(fields=['zip']),
        ]

    def __str__(self):
        return '{}, {}, {} {}, {}'.format(self.street, self.city, self.state, self.zip, self.country)


class AddressDescriptor(ForwardManyToOneDescriptor):

    def _to_python(self, value):
        if value is None or value == '':
            return None

        if isinstance(value, Address):
            return value

        # If we have an integer, assume it is a model primary key.
        elif isinstance(value, int):
            return value

        elif isinstance(value, str):
            # ex address: 2050 Goodpasture Loop, Eugene, OR 97401, USA
            address_bits = value.split(',')

            if len(address_bits) is 4:
                state_zip_bits = address_bits[2].strip().split(' ')
                obj = Address(street=address_bits[0].strip(), city=address_bits[1].strip(), state=state_zip_bits[0],
                              zip=state_zip_bits[1], country=address_bits[3].strip())
                obj.save()
                return obj

        raise ValidationError('Invalid address value.')

    def __set__(self, inst, value):
        super(AddressDescriptor, self).__set__(inst, self._to_python(value))


class AddressField(models.ForeignKey):
    description = 'An address'

    def __init__(self, *args, **kwargs):
        kwargs['to'] = 'Address'
        super(AddressField, self).__init__(*args, **kwargs)

    def contribute_to_class(self, cls, name, virtual_only=False):
        super().contribute_to_class(cls, name, virtual_only=virtual_only)
        setattr(cls, self.name, AddressDescriptor(self))

    def formfield(self, **kwargs):
        defaults = {
            'form_class': forms.CharField
        }
        defaults.update(kwargs)
        return models.Field.formfield(self, **defaults)
        # return models.CharField().formfield(**kwargs)


###################
#  Profile
###################


PHONE_REGEX = RegexValidator(regex=r'^\+?(1-)?\d{3}-\d{3}-\d{4}$',
                             message="Phone number must be entered in the format: '999-999-9999'.")


class Profile(models.Model):
    user = models.OneToOneField("auth.User")
    monthly_contribution = MoneyField("Monthly Contribution", decimal_places=2)
    phone_number = models.CharField("Contact Number", validators=[
        PHONE_REGEX], max_length=15)
    phone_number_2 = models.CharField("Alternate Contact Number", validators=[
        PHONE_REGEX], blank=True, max_length=15)
    drop_site = models.CharField("Drop Site", blank=True, max_length=255)
    notes = RichTextField("Customer Notes", blank=True)
    invoice_notes = models.TextField("Invoice Notes", blank=True,
                                     help_text="Use &lt;br/&gt; to enter a newline, and &lt;b&gt;My Text&lt;/b&gt; to make something bold.")
    start_date = models.DateField("CSA Start Date", blank=True, null=True)
    stripe_customer_id = models.CharField(
        blank=True, null=True, max_length=255)
    stripe_subscription_id = models.CharField(
        blank=True, null=True, max_length=255)
    payment_method = models.CharField(blank=True, null=True,
                                      choices=[
                                          ('CC', 'Credit Card'), ('ACH', 'Bank Account'), ('CRYPTO', 'Crypto')],
                                      max_length=255)
    ach_status = models.CharField(blank=True, null=True, max_length=20,
                                  choices=[('NEW', 'Unverified'), ('VERIFYING', 'Verifying'), ('VERIFIED', 'Verified'),
                                           ('FAILED', 'Verification Failed')])
    paid_signup_fee = models.BooleanField(default=False)
    can_order_dairy = models.BooleanField("Has had dairy conversation", default=False)
    join_dairy_program = models.BooleanField(
        "Join Raw Dairy Program",
        help_text="I would like to join the Raw Dairy program. I understand that I will be charged a $50 herd-share fee when making my first payment and will need to talk to the Dairy Manager before gaining access to raw dairy products. We'll be in touch soon.",
        default=False)
    payment_agreement = models.BooleanField(
        "I agree to make monthly payments in order to maintain my membership with the FFCSA for 6 months, with a minimium of $172 per month.",
        default=False)
    signed_membership_agreement = models.BooleanField(default=False,
                                                      help_text="We have a signed Member Liability Document of file.")
    non_subscribing_member = models.BooleanField(default=False,
                                                 help_text="Non-subscribing members are allowed to make payments to their ffcsa account w/o having a monthly subscription")
    plastic_bags = models.BooleanField(default=False,
                                          help_text="Please pack small items in a plastic bag.")
    allow_substitutions = models.BooleanField(default=True,
                                              help_text="I am okay with substitutions when an item I ordered is no longer available. We do our best to pack what you have ordered, however on occasion crops will not be ready to harvest, etc. We can provide a substitution, or we can credit your account.")
    weekly_emails = models.BooleanField(default=True, verbose_name="Receive Weekly Emails",
                                        help_text="Receive weekly newsletter and reminder emails.")
    google_person_id = models.TextField(
        null=True, help_text="Google Person resource id", blank=True)
    discount_code = models.ForeignKey(
        'shop.DiscountCode', blank=True, null=True, on_delete=models.PROTECT)
    home_delivery = models.BooleanField(default=False, verbose_name="Home Delivery",
                                        help_text="Available in Eugene, Corvallis, and Springfield for a $5 fee. This fee is waived for all orders over ${}.".format(
                                            settings.FREE_HOME_DELIVERY_ORDER_AMOUNT))
    delivery_address = AddressField(null=True, blank=True)
    delivery_notes = models.TextField("Special Delivery Notes", blank=True)
    num_adults = models.IntegerField("How many adults are in your family?", default=0,
                                     validators=[validators.MinValueValidator(1)]
                                     )

    class Meta:
        indexes = [
            models.Index(fields=['drop_site']),
        ]

    @property
    def joined_before_dec_2017(self):
        # use early nov b/c dec payments are received in nov
        return self.user.date_joined.date() <= datetime.date(2017, 11, 5)

    @property
    def is_member(self):
        # TODO this is not correct
        # TODO fix this for one-time orders
        return self.paid_signup_fee

    @property
    def is_subscribing_member(self):
        # TODO fix this for one-time orders
        return True
        # return (self.is_member and (self.stripe_subscription_id is not None)) or self.user.id == 5

    def __str__(self):
        if self.user.last_name and self.user.first_name:
            return "{}, {}".format(self.user.last_name, self.user.first_name)

        return self.user.get_username()

    def __getattr__(self, item):
        if item == 'home_delivery':
            return self._get_home_delivery()
        return super().__getattribute__(item)

    def _get_home_delivery(self):
        if settings.HOME_DELIVERY_ENABLED:
            return self._home_delivery

        return False


###################
#  DropSite
###################

class DropSiteInfo(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    drop_site_template_name = models.CharField('Drop Site Template Name', max_length=255)
    last_version_received = models.TextField('Last Version Received', null=True, blank=True)

    def __str__(self):
        return self.drop_site_template_name


###################
#  Payment
###################


class Payment(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    date = models.DateField('Payment Date', default=datetime.date.today)
    amount = models.DecimalField('Amount', max_digits=10, decimal_places=2)
    pending = models.BooleanField('Pending', default=False)
    notes = models.TextField('Notes', null=True, blank=True)
    charge_id = models.CharField(max_length=255, null=True, blank=True)
    is_credit = models.BooleanField(default=False)

    objects = PaymentManager()

    def __str__(self):
        return "%s, %s - %s - %s for $%s" % (
            self.user.last_name, self.user.first_name, self.date, 'Credit' if self.is_credit else 'Payment',
            self.amount)


class Recipe(Page, RichText):
    """
    A recipe with list of products on the website.
    """
    featured_image = FileField(verbose_name="Featured Image",
                               upload_to=upload_to(
                                   "shop.Recipe.featured_image", "shop"),
                               format="Image", max_length=255, null=True, blank=True)
    products = models.ManyToManyField("shop.Product", blank=True,
                                      verbose_name="Products",
                                      through="RecipeProduct")

    class Meta:
        verbose_name = "Recipe"
        verbose_name_plural = "Recipes"


class RecipeProduct(models.Model):
    recipe = models.ForeignKey(
        Recipe, verbose_name="Recipe", on_delete=models.CASCADE)
    product = models.ForeignKey(
        "shop.Product", verbose_name="Product", on_delete=models.CASCADE)
    quantity = models.IntegerField("Quantity", default=1)
