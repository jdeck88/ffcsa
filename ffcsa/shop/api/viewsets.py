from django.shortcuts import get_object_or_404
from django.db.models import  Q
from rest_framework import viewsets
from rest_framework.decorators import detail_route, list_route
from rest_framework.response import Response

from ffcsa.shop.utils import recalculate_cart

from ffcsa.shop.models.Cart import Cart
from ffcsa.shop.models.Product import Product, ProductVariation
from ffcsa.shop.models.Category import Category

from .serializers import *


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    queryset = Product.objects.all()

    def list(self, request):
        # note - need to add the filters manually as django filters
        # can not be installed with current django version which is
        # required to run Mezzanine

        # queryset = Product.objects.filter(categories__title__icontains=filt_category)
        
        queryset = Product.objects.all()
        filt_category = request.GET.get('category')
        if filt_category:
            queryset = Product.objects.filter(
                Q(categories__title=filt_category) | Q(categories__parent__title=filt_category)    
            )
        queryset = self.paginate_queryset(queryset)
        serializer = ProductDataSerializer(queryset, many=True)
        return self.get_paginated_response(serializer.data)

    @list_route(methods=['get'])
    def get_parent_sub_categories(self, request):
        cats = Category.parent_sub_categories()
        return Response(cats)


class ProductVariationViewSet(viewsets.ModelViewSet):
    serializer_class = ProductVariationSerializer
    queryset = ProductVariation.objects.all()

    def list(self, request):
        return Response([])

    @detail_route(methods=['post'])
    def add_to_cart(self, request, pk=None):
        """
        Add product variation to cart
        """
        product_variation = get_object_or_404(ProductVariation, pk=pk)
        quantity = request.data.get('quantity', 1)
        request.cart.add_item(product_variation, int(quantity))
        recalculate_cart(request)
        return Response({'OK': 'OK'})


class CartViewSet(viewsets.ModelViewSet):
    serializer_class = CartSerializer
    queryset = Cart.objects.all()

    def list(self, request):
        # treating this one as retrive not list
        serializer = self.get_serializer(request.cart)
        return Response(serializer.data)

    @list_route(methods=['post'])
    def clear(self, request):
        # clears out the cart
        request.cart.clear()
        return Response({})
