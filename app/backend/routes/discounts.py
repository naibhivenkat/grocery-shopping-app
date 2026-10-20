"""Single promotion selection and exact deterministic paise allocations."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from routes.khata import KhataError, _money_paise

RULE_FIELDS = {'discount_type', 'discount_value', 'minimum_order_amount', 'maximum_discount_amount'}


def _rule_paise(value, *, allow_zero=False):
    amount = _money_paise(value, allow_zero=allow_zero)
    if Decimal(str(value)) * 100 != amount:
        raise KhataError('Discount amounts must have at most two decimal places')
    return amount


def rules(content):
    kind = content.get('discount_type')
    if kind is None:
        kind = 'none'
    if not isinstance(kind, str) or kind not in {'none', 'percentage', 'fixed'}:
        raise KhataError('discount_type must be none, percentage or fixed')
    value = content.get('discount_value')
    if kind == 'percentage':
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise KhataError('Percentage must be a number from 0.01 to 100')
        try:
            percentage = Decimal(str(value))
            if not percentage.is_finite() or not 0 < percentage <= 100 or percentage != percentage.quantize(Decimal('0.01')):
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise KhataError('Percentage must be from 0.01 to 100 with at most two decimal places') from None
        value = float(percentage)
    elif kind == 'fixed':
        value = _rule_paise(value) / 100
    else:
        if value is not None and _rule_paise(value, allow_zero=True) != 0:
            raise KhataError('Advertising-only promotions cannot specify a discount value')
        value = 0
    minimum = _rule_paise(0 if content.get('minimum_order_amount') is None else content['minimum_order_amount'], allow_zero=True) / 100
    maximum = content.get('maximum_discount_amount')
    if maximum is not None:
        maximum = _rule_paise(maximum) / 100
    if kind == 'none':
        minimum, maximum = 0, None
    return {'discount_type': kind, 'discount_value': value,
            'minimum_order_amount': minimum, 'maximum_discount_amount': maximum}


def allocate(lines, discount):
    """lines=(stable item ID, gross paise); no line receives more than its gross."""
    gross = sum(amount for _, amount in lines)
    if type(discount) is not int or not 0 <= discount <= gross:
        raise KhataError('Discount cannot exceed the order subtotal')
    if not gross:
        return {identifier: 0 for identifier, _ in lines}
    result = {identifier: discount * amount // gross for identifier, amount in lines}
    remainder = discount - sum(result.values())
    ranking = sorted(lines, key=lambda line: (-(discount * line[1] % gross), line[0]))
    for identifier, _ in ranking[:remainder]:
        result[identifier] += 1
    return result


def best_promotion(snapshots, vendor_id, lines, now=None):
    """Caller reads promotions inside the same stock/order transaction."""
    now = now or datetime.now(timezone.utc)
    choices = []
    for snapshot in snapshots:
        promotion = snapshot.to_dict() or {}
        try:
            if (promotion.get('vendor_id') != vendor_id or promotion.get('shop_id') != vendor_id
                    or promotion.get('status') != 'approved' or promotion.get('is_paused')
                    or type(promotion.get('revision')) is not int
                    or promotion.get('approved_revision') != promotion['revision']):
                continue
            starts = datetime.fromisoformat(promotion['starts_at'].replace('Z', '+00:00'))
            ends = datetime.fromisoformat(promotion['ends_at'].replace('Z', '+00:00'))
            if starts.tzinfo is None or ends.tzinfo is None or not starts <= now < ends:
                continue
            normalized = {**rules(promotion), 'target_type': promotion.get('target_type'),
                          'product_id': promotion.get('product_id'), 'shop_id': vendor_id}
            if normalized['discount_type'] == 'none':
                continue
            if promotion.get('target_type') == 'shop':
                eligible = list(lines)
            elif promotion.get('target_type') == 'product':
                eligible = [line for line in lines if line[0] == promotion.get('product_id')]
            else:
                continue
            gross = sum(amount for _, amount in eligible)
            if not gross or gross < _money_paise(normalized['minimum_order_amount'], allow_zero=True):
                continue
            if normalized['discount_type'] == 'fixed':
                discount = _money_paise(normalized['discount_value'])
            else:
                discount = int((Decimal(gross) * Decimal(str(normalized['discount_value'])) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            if normalized['maximum_discount_amount'] is not None:
                discount = min(discount, _money_paise(normalized['maximum_discount_amount'], allow_zero=True))
            discount = min(gross, discount)
            if discount:
                choices.append((discount, snapshot.id, promotion['revision'], normalized, eligible))
        except (KhataError, ValueError, TypeError, KeyError, InvalidOperation):
            continue
    if not choices:
        return {'amount_paise': 0, 'shares': {}, 'promotion_id': None, 'promotion_revision': None, 'promotion_rules': None}
    discount, identifier, revision, normalized, eligible = sorted(choices, key=lambda choice: (-choice[0], choice[1]))[0]
    return {'amount_paise': discount, 'shares': allocate(eligible, discount),
            'promotion_id': identifier, 'promotion_revision': revision, 'promotion_rules': normalized}
