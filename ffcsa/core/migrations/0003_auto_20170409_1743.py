# -*- coding: utf-8 -*-
# Generated by Django 1.10.6 on 2017-04-09 17:43
from __future__ import unicode_literals

import cartridge.shop.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ffcsa_core', '0002_auto_20170408_2208'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='weekly_budget',
            field=cartridge.shop.fields.MoneyField(blank=True, decimal_places=0, max_digits=10, null=True, verbose_name='Weekly Budget'),
        ),
    ]