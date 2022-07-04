from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from django.db.models import  Q, query
from rest_framework import viewsets
from rest_framework import mixins
from rest_framework.decorators import detail_route, list_route
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import pagination

from ffcsa.shop.utils import recalculate_cart, recalculate_product_price

from ffcsa.shop.models.Cart import Cart, CartItem
from ffcsa.shop.models.Product import Product, ProductVariation
from ffcsa.shop.models.Category import Category
from ffcsa.shop.models.Order import Order

from .serializers import *



class CustomPagination(pagination.PageNumberPagination):
    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'num_pages': self.page.paginator.num_pages,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data
        })


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    queryset = Product.objects.filter(available=True)
    pagination_class = CustomPagination

    def list(self, request):
        # note - need to add the filters manually as django filters
        # can not be installed with current django version which is
        # required to run Mezzanine

        queryset = Product.objects.filter(available=True)
        
        # filter category
        if (filt_category := request.GET.get('category')):
            # queryset to get the products/subproducts
            queryset = Product.objects.filter(
                (Q(categories__title=filt_category) | Q(categories__parent__title=filt_category)) & Q(available=True)
            )

        # filter query
        query = request.GET.get('query')
        queryset = queryset.filter(Q(title__icontains=query) | Q(categories__title__icontains=query) | Q(categories__parent__title__icontains=query))
        
        queryset = queryset.exclude(categories=None).order_by('title')

        queryset = self.paginate_queryset(queryset.distinct())
        serializer = ProductDataSerializer(queryset, many=True)

        data = serializer.data
        
        # Increase products price by 5% for non-members
        if not request.user.is_authenticated():
            for product in data:
                product['price'] = recalculate_product_price(product['price'])
        return self.get_paginated_response(data)

    @list_route(methods=['get'])
    def get_parent_sub_categories(self, request):
        cats = Category.shop_menu_categories(request.user.is_authenticated)
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
        
        # increase item quantity if item already in cart 
        item = request.cart.items.filter(variation=product_variation).first()
        if item:
            item.update_quantity(item.quantity + 1)
        else:
            request.cart.add_item(product_variation, 1)
        
        recalculate_cart(request)
        return Response({'OK': 'OK'})


class CartViewSet(viewsets.ModelViewSet):
    serializer_class = CartSerializer
    queryset = Cart.objects.all()

    def list(self, request):
        # treating this one as retrive not list
        serializer = self.get_serializer(request.cart)
        return Response(serializer.data)


    @detail_route(methods=['post'])
    def increase_item(self, request, pk=None):
        item = get_object_or_404(CartItem, pk=pk)
        item.update_quantity(item.quantity + 1)

        request.cart.last_updated = now()
        request.cart.save()
        return Response({'message': 'Item increased'})
    
    @detail_route(methods=['post'])
    def decrease_item(self, request, pk=None):
        item = get_object_or_404(CartItem, pk=pk)
        
        if (item.quantity - 1) == 0:
            item.delete()
            return Response({'message': 'Item decreased'})
            
        item.update_quantity(item.quantity - 1)

        request.cart.last_updated = now()
        request.cart.save()
        return Response({'message': 'Item decreased'})
    
    @detail_route(methods=['post'])
    def remove_item(self, request, pk=None):
        # remove item from cart
        item = get_object_or_404(CartItem, pk=pk)
        item.delete()

        request.cart.last_updated = now()
        request.cart.save()
        return Response({'message': 'Item removed'})

    @list_route(methods=['post'])
    def clear(self, request):
        # clears out the cart
        request.cart.clear()
        return Response({})


class OrderViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = OrderSerializer
    queryset = Order.objects.all()
    permission_classes = [IsAuthenticated]

    def list(self, request):
        queryset = self.queryset.filter(user_id=request.user.id)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)