from __future__ import absolute_import, unicode_literals

default_app_config = "ffcsa.core.apps.CoreConfig"


# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
from ffcsa.celery import app as celery_app

__all__ = ["celery_app"]
