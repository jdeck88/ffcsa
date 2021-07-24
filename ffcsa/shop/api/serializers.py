from ffcsa.shop import fields
from rest_framework import serializers

from ffcsa.shop.models.Cart import Cart, CartItem
from ffcsa.shop.models.Product import Product, ProductSeason, ProductVariation
from ffcsa.shop.models.Order import Order



# used for all CRUD operations
class ProductVariationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariation
        fields = '__all__'

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'


# used for all CRUD operations


# used to display some data
class ProductVariationDataSerializer(serializers.ModelSerializer):
    is_unlimited = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariation
        fields = ['id', 'in_inventory', 'is_frozen', 'unit_price', 'sku', 
                    'options', 'unit', 'is_unlimited', 'number_in_stock']
    
    def get_is_unlimited(self, obj):
        # if number_in_stock is None means that the product amount
        # is unlimited
        return obj.number_in_stock is None


class ProductDataSerializer(serializers.ModelSerializer):
    url         = serializers.CharField(source='get_absolute_url', read_only=True)
    variations  = ProductVariationDataSerializer(many=True)
    seasons     = serializers.SerializerMethodField()
    has_in_stock_variations = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = ['id', 'slug', 'title', 'image', 'price', 'is_dairy', 'categories', 'url', 
                 'vendor', 'variations', 'content', 'seasons', 'has_in_stock_variations']

    def get_seasons(self, obj):
        # return list of season names for this Product
        return obj.seasons.values_list('name', flat=True)

    def get_has_in_stock_variations(self, obj):
        # if all variations are out of stock, then main product is too
        variations_stock = [variation.number_in_stock != 0 for variation in obj.variations.all()]
        return any(variations_stock)


class CartItemSerializer(serializers.ModelSerializer):
    # image = serializers.CharField(source='image.file')
    product_id = serializers.CharField(source='variation.product.id')   # delete me
    variation_id = serializers.CharField(source='variation.id')
    image = serializers.SerializerMethodField()
    all_quantity_in_cart = serializers.SerializerMethodField()

    # note - 'description' here is like the title
    
    class Meta:
        model = CartItem
        fields = ('id', 'product_id', 'variation_id', 'description', 'unit_price', 'image', 'quantity', 'all_quantity_in_cart')

    def get_image(self, obj):
        if obj.image:
            return str(obj.image.file)

        # TODO - return default product image if none were given
        return ''

    def get_all_quantity_in_cart(self, obj):
        # return True if all item stock-available quantity already in Cart
        return obj.quantity == obj.variation.number_in_stock


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True)
    total_price = serializers.CharField()
    delivery_fee = serializers.IntegerField()

    class Meta:
        model = Cart
        fields = ('id', 'attending_dinner', 'items', 'total_price', 'delivery_fee', 'remaining_budget')


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        # fields = '__all__'
        fields = ('id', 'time', 'total', 'invoice')