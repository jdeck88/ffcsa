from rest_framework import routers

from ffcsa.shop.api.viewsets import *

router = routers.SimpleRouter()
router.register('products', ProductViewSet, base_name='products')
router.register('product_variations', ProductVariationViewSet, base_name='product_variations')
router.register('cart', CartViewSet, base_name='api_cart')
router.register('orders', OrderViewSet, base_name='orders')
