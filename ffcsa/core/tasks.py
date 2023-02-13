from __future__ import absolute_import, unicode_literals
from datetime import datetime

from celery.signals import task_failure
from django.core import management
from django.utils.timezone import utc

from ffcsa.celery import app
from ffcsa.shop.models.Cart import Cart


# from celery.utils.log import get_task_logger
# logger = get_task_logger(__name__)

@task_failure.connect()
def celery_task_failure_email(**kwargs):
    from django.core.mail import mail_admins
    import socket
    """ celery 4.0 onward has no method to send emails on failed tasks
    so this event handler is intended to replace it
    """
    subject = "[{queue_name}@{host}] Error: Task {sender.name} ({task_id}): {exception}".format(
        queue_name="celery",  # `sender.queue` doesn't exist in 4.1?
        host=socket.gethostname(),
        **kwargs
    )
    message = """Task {sender.name} with id {task_id} raised exception:\n
{exception!r}\n
Task was called with args: {args} kwargs: {kwargs}.\n
The contents of the full traceback was:
{einfo}
    """.format(
        **kwargs
    )
    mail_admins(subject, message)


@app.task(bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_kwargs={'max_retries': 8})
def send_weekly_orders(self):
    """
    """
    management.call_command("cart")
    management.call_command("send_weekly_orders", "--send-orders")
    return True


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
