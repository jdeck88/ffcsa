# -*- coding: utf-8 -*-
# Generated by Django 1.10.8 on 2019-04-03 17:57
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ffcsa_core', '0021_auto_20190403_1056'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='can_order',
            field=models.BooleanField(default=False, verbose_name='Has had dairy conversation'),
        ),
    ]