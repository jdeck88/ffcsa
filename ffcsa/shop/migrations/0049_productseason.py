# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2021-01-21 18:09
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0048_auto_20201030_1226'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductSeason',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(blank=True, max_length=200)),
                ('name', models.SlugField(max_length=200)),
            ],
        ),
    ]
