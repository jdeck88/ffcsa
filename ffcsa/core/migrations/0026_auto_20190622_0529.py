# -*- coding: utf-8 -*-
# Generated by Django 1.11.20 on 2019-06-22 12:29
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ffcsa_core', '0025_auto_20190603_2027'),
    ]

    operations = [
        migrations.RenameField(
            model_name='profile',
            old_name='notes',
            new_name='invoice_notes',
        ),
    ]