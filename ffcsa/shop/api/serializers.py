from ffcsa.shop import fields
from rest_framework import serializers

from ffcsa.shop.models.Cart import Cart, CartItem
from ffcsa.shop.models.Product import Product, ProductSeason, ProductVariation



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
        return not obj.number_in_stock # check if None or empty string


class ProductDataSerializer(serializers.ModelSerializer):
    url         = serializers.CharField(source='get_absolute_url', read_only=True)
    variations  = ProductVariationDataSerializer(many=True)
    seasons     = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = ['id', 'slug', 'title', 'image', 'price', 'num_in_stock', 'is_dairy',
                 'categories', 'url', 'vendor', 'variations', 'content', 'seasons']

    def get_seasons(self, obj):
        # return list of season names for this Product
        return obj.seasons.values_list('name', flat=True)


class CartItemSerializer(serializers.ModelSerializer):
    # image = serializers.CharField(source='image.file')
    product_id = serializers.CharField(source='variation.product.id')   # delete me
    variation_id = serializers.CharField(source='variation.id')
    image = serializers.SerializerMethodField()

    # note - 'description' here is like the title
    
    class Meta:
        model = CartItem
        fields = ['product_id', 'variation_id', 'description', 'unit_price', 'image', 'quantity']

    def get_image(self, obj):
        if obj.image:
            return obj.image.file.url

        # TODO - return default product image if none were given
        return ''

    def get_total_price(self, obj):
        return obj.item_total_price()


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True)
    total_price = serializers.CharField()
    delivery_fee = serializers.IntegerField()

    class Meta:
        model = Cart
        fields = ['id', 'attending_dinner', 'items', 'total_price', 'delivery_fee']
