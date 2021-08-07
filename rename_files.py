import re

from ffcsa.shop.models import Product




for product in Product.objects.all():
    # print(product.title)

    unit_expression = re.compile(r'^\w{1,2},')
    if re.match(unit_expression, product.title):
        unit = re.search(unit_expression, product.title)[0]
        product.title = product.title.replace(unit, '').strip()

        # print(product.title)
    

    # print(product.title)
    
    weight_expression = re.compile(r'\(.*\)$')
    if re.match(weight_expression, product.title):
        print(product.title)
        weight = re.search(weight_expression, product.title)[0]
        product.title = product.title.replace(weight, '').strip()


    # if '(' in product.title:
    #     print(product.title)








    # print(product.title)

    # # parse product unit
    # if ',' in product.title:
    #     splited_title = product.title.split(',')
    #     unit = splited_title[0]
    #     product.title = ''.join(splited_title[1:])
    #     # print(unit, product.title)
    
    # if '(' in product.title:
    #     splited_title = product.title.split('(')
    #     # print(splited_title)
