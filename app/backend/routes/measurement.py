"""Canonical integer quantities; money is rounded once per purchased line."""
from decimal import Decimal, ROUND_HALF_UP
from routes.khata import KhataError

UNITS = {'g': ('g', 1), 'kg': ('g', 1000), 'l': ('ml', 1000), 'piece': ('piece', 1), 'pack': ('pack', 1)}
FIELDS = {'selling_unit', 'pricing_quantity', 'stock_unit'}


def explicit(item):
    return any(key in item for key in FIELDS)


def metadata(item):
    if not explicit(item):
        return {'selling_unit': 'piece', 'pricing_quantity': 1, 'stock_unit': 'piece'}
    unit = item.get('selling_unit')
    if not isinstance(unit, str) or unit not in UNITS:
        raise KhataError('Choose g, kg, l, piece or pack')
    quantity = item.get('pricing_quantity')
    if type(quantity) is not int or not 1 <= quantity <= 10000000:
        raise KhataError('pricing_quantity must be a positive canonical integer up to 10000000')
    if item.get('stock_unit') != UNITS[unit][0]:
        raise KhataError('stock_unit does not match the selling unit')
    return {key: item[key] for key in FIELDS}


def acknowledge(item, unit):
    data = metadata(item)
    if (explicit(item) or unit is not None) and unit != data['stock_unit']:
        raise KhataError('Refresh or update the app and confirm the product quantity unit')
    return data


def same_base(order, item):
    if metadata(order)['stock_unit'] != metadata(item)['stock_unit']:
        raise KhataError('Inventory measurement changed; reconciliation required', 409)


def line_paise(price_paise, quantity, item):
    basis = metadata(item)['pricing_quantity']
    total = int((Decimal(price_paise) * quantity / basis).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if not 0 < total <= 1000000000:
        raise KhataError('Measured total must be at least 0.01 INR and within the supported limit')
    return total


def quantity_label(quantity, item):
    data = metadata(item)
    value = Decimal(str(quantity)) / UNITS[data['selling_unit']][1]
    return f"{format(value.normalize(), 'f')} {data['selling_unit']}"
