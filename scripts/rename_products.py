import re
# import time
# import pandas as pd
from ffcsa.shop.models import Product



# # create backup of products names
# df = pd.DataFrame(Product.objects.all().values_list('id', 'title'), columns=['id', 'name'])
# df.to_csv(f'products-{int(time.time())}.csv', index=None)



# rename product `#, Potatoes, Sierra Gold, #2` cuz it match on both sides
try:
    product = Product.objects.get(title='#, Potatoes, Sierra Gold, #2')
    product.title = product.title.replace('#, ', '')
    product.save()
except:
    pass

try:
    product = Product.objects.get(title='ea, Raw Fresh Sweet Cream (1 pt)')
    product.title = product.title.replace('ea, ', '')
    product.save()
except:
    pass




def clean_unit(str):
    return str.replace(',', '').replace('(', '').replace(')', '').strip()



product_list = []

# parse product weight
weight_expression = re.compile(r'\(.*(#|oz|gal|qt|lbs|lb|pieces|count|bag.*)\)|\(.*\)#|(-|,)\s\d\"|\s\d/\d#\s$|,\s#\d$|\s\d*oz$|(-\s|\.|,\s*\d).*(lb|qt|#$)|^\d+(/\d|\.\d)*\s*(#|bu|qt|oz|pk|gal),*|^#,\s')
for product in Product.objects.all():

    for variation in product.variations.all():
        # * Weight
        weight_search = weight_expression.search(variation.title)

        weight = weight_search.group() if weight_search else ''


        # remove the weight from the title
        new_title = variation.title.replace(weight, '').strip()

        # * Unit
        unit_expression = re.compile(r'^.*(ea|bu|pt|bag|doz|pk|flat|box|qt|oz),|\(.*pt\)')
        unit_search = unit_expression.search(new_title)

        unit = unit_search.group() if unit_search else ''

        # remove unit from the title
        new_title = new_title.replace(unit, '').strip()

        # Clean unit and weight
        weight = clean_unit(weight)
        unit = clean_unit(unit)

        # Assing ea to lb
        if '#' in weight or 'lb' in weight:
            unit = 'ea'

        # final cleaning for weight
        weight = re.sub('^-', '', weight).strip()

        # only # with no number
        if weight == '#':
            unit, weight = 'lb', ''

        if variation.default:
            product.title = new_title

        if variation._title:
            variation._title = new_title
        else:
            product.title = new_title
        variation.weight = weight
        variation.unit = unit
        variation.save()
        product.copy_default_variation()
        product.save()



    # product_list.append([product.id, product.title, weight, unit, new_title])



# # create backup of products names
# df = pd.DataFrame(product_list, columns=['id', 'old_title', 'weight', 'unit', 'new_title'])
# df.to_csv(f'products-new.csv', index=None)


