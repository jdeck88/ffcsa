from __future__ import absolute_import, unicode_literals
from datetime import datetime

from django.utils.timezone import utc

from ffcsa.celery_tasks import app
from ffcsa.shop.models.Cart import Cart

# from celery.utils.log import get_task_logger
# logger = get_task_logger(__name__)


@app.task(bind=True)
def clean_anonymous_carts(self):
    """
    if a cart (for non-members) gets inactive for 20mins we remove it
    """

    # time to remove cart
    CART_TIMEOUT = 20 * 60

    carts = Cart.objects.filter(user_id=None)
    for cart in carts:
        now = datetime.utcnow().replace(tzinfo=utc)
        timediff = now - cart.last_updated
        if timediff.total_seconds() > CART_TIMEOUT:
            cart.delete()
