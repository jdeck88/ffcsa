# Source https://www.namm.org/standards/implementation-guide-/codes-tables/unit-measurement-uom-codes

UNITS = (
    ('Bag', 'BAG'),
    ('Bunch', 'BU'),
    ('Case', 'CS'),
    ('Dozen', 'DZ'),
    ('Each', 'EA'),
    ('Gallon', 'GAL'),
    ('Pack', 'PK'),
)

from ffcsa.shop.models.Product import ProductVariationUnit
for unit in UNITS:
    ProductVariationUnit.objects.get_or_create(name=unit[0], code=unit[1])