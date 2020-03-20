# -*- coding: utf-8 -*-
# Generated by Django 1.10.6 on 2017-03-28 23:09
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0002_cart_user_id'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='productvariation',
            name='option1',
        ),
        migrations.RemoveField(
            model_name='productvariation',
            name='option2',
        ),
        migrations.AddField(
            model_name='product',
            name='content_model',
            field=models.CharField(editable=False, max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name='productoption',
            name='type',
            field=models.IntegerField(verbose_name='Type'),
        ),
    ]