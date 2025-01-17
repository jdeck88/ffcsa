from rest_framework import serializers

from ffcsa.shop.models.Cart import Cart, CartItem
from ffcsa.shop.models.Product import Product, ProductImage, ProductVariation, ProductVariationUnit
from ffcsa.shop.models.Order import Order
from ffcsa.shop.models.Vendor import Vendor


# used for all CRUD operations
class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'


class ProductVariationSerializer(serializers.ModelSerializer):
    product = ProductSerializer()
    
    class Meta:
        model = ProductVariation
        fields = '__all__'


# used for all CRUD operations
class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ('id', 'file', 'description')


# used to display some data
class VendorDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = '__all__'
        # fields = ('id', 'title', )


# used to display some data
class ProductVariationUnitDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariationUnit
        fields = '__all__'


# used to display some data
class ProductVariationDataSerializer(serializers.ModelSerializer):
    image = ProductImageSerializer()
    addable = serializers.SerializerMethodField()
    vendors = VendorDataSerializer(many=True)
    # unit = ProductVariationUnitDataSerializer()

    class Meta:
        model = ProductVariation
        fields = ('id', 'title', 'short_description', 'in_inventory', 'is_frozen', 'unit_price', 'sku', 'options', 'unit',
                  'weight', 'number_in_stock', 'live_num_in_stock', 'image', 'addable', 'vendors')

    def get_addable(self, obj):
        # if number_in_stock is None means that the product amount
        # is unlimited
        return obj.number_in_stock is None or obj.number_in_stock > 0


class ProductDataSerializer(serializers.ModelSerializer):
    url = serializers.CharField(source='get_absolute_url', read_only=True)
    variations = ProductVariationDataSerializer(many=True)
    seasons = serializers.SerializerMethodField()
    has_in_stock_variations = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = ('id', 'slug', 'title', 'short_description', 'image', 'price', 'is_dairy', 'categories', 'url', 'unit',
                  'weight', 'vendor', 'variations', 'content', 'seasons', 'has_in_stock_variations')

    def get_seasons(self, obj):
        # return list of season names for this Product
        return obj.seasons.values_list('name', flat=True)

    def get_has_in_stock_variations(self, obj):
        # if all variations are out of stock, then main product is too
        variations_stock = [variation.live_num_in_stock() != 0 for variation in obj.variations.all()]
        return any(variations_stock)


class CartItemSerializer(serializers.ModelSerializer):
    # image = serializers.CharField(source='image.file')
    variation = ProductVariationSerializer()
    product_id = serializers.CharField(source='variation.product.id')   # delete me
    variation_id = serializers.CharField(source='variation.id')
    image = serializers.SerializerMethodField()
    addable = serializers.SerializerMethodField()

    # note - 'description' here is like the title
    
    class Meta:
        model = CartItem
        fields = ('id', 'product_id', 'variation_id', 'description', 'unit_price', 'total_price', 'variation',
                'image', 'quantity', 'addable')

    def get_image(self, obj):
        if obj.image:
            return str(obj.image.file)

        # TODO - return default product image if none were given
        return ''

    def get_addable(self, obj):
        # returns whether or not you can add an item
        live_num_in_stock = obj.variation.live_num_in_stock()

        if (is_unlimited := live_num_in_stock == None):
            return True
   
        if live_num_in_stock > 0:
            return obj.quantity != obj.variation.number_in_stock
        
        return False


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True)
    total_price = serializers.CharField()
    delivery_fee = serializers.IntegerField()

    class Meta:
        model = Cart
        fields = ('id', 'attending_dinner', 'items', 'total_price', 'delivery_fee', 
                    'remaining_budget', 'upsell_products', 'last_updated')


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        # fields = '__all__'
        fields = ('id', 'time', 'total', 'invoice')