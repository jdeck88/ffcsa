# Source https://www.namm.org/standards/implementation-guide-/codes-tables/unit-measurement-uom-codes

UNITS = (
    ('Bag', 'BAG'),
    ('Bucket', 'BKT'),
    ('Bundle', 'BND'),
    ('Bowl', 'BOWL'),
    ('Box', 'BX'),
    ('Card', 'CRD'),
    ('Centimeters', 'CM'),
    ('Case', 'CS'),
    ('Carton', 'CTN'),
    ('Dozen', 'DZ'),
    ('Each', 'EA'),
    ('Foot', 'FT'),
    ('Gallon', 'GAL'),
    ('Gross', 'GROSS'),
    ('Inches', 'IN'),
    ('Kit', 'KIT'),
    ('Lot', 'LOT'),
    ('Meter', 'M'),
    ('Millimeter', 'MM'),
    ('Piece', 'PC'),
    ('Pack', 'PK'),
    ('Pack 100', 'PK100'),
    ('Pack 50', 'PK50'),
    ('Pair', 'PR'),
    ('Rack', 'RACK'),
    ('Roll', 'RL'),
    ('Set', 'SET'),
    ('Set of 3', 'SET3'),
    ('Set of 4', 'SET4'),
    ('Set of 5', 'SET5'),
    ('Single', 'SGL'),
    ('Sheet', 'SHT'),
    ('Square ft', 'SQFT'),
    ('Tube', 'TUBE'),
    ('Yard', 'YD'),
)

from ffcsa.shop.models.Product import ProductVariationUnit
for unit in UNITS:
    ProductVariationUnit.objects.get_or_create(name=unit[0], code=unit[1])