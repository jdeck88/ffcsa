# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-10-30 19:26
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ffcsa_core', '0051_auto_20200724_1155'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='profile',
            name='no_plastic_bags',
        ),
        migrations.AddField(
            model_name='profile',
            name='plastic_bags',
            field=models.BooleanField(default=False, help_text='Please pack small items in a plastic bag.'),
        ),
    ]
