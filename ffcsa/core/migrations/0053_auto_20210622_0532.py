# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2021-06-22 12:32
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ffcsa_core', '0052_auto_20201030_1226'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='join_dairy_program',
            field=models.BooleanField(default=False, help_text="I would like to join the Dairy program. I understand that I will be charged a $50 herd-share fee when making my first payment and will need to talk to the Dairy Manager before gaining access to dairy products. We'll be in touch soon.", verbose_name='Join Dairy Program'),
        ),
    ]