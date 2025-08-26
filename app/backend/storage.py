from collections import defaultdict

items_by_shop = defaultdict(list)  # ✅ Now organized by shop_id

shops = []
orders = []

# Mapping of shopkeeper_id → list of shop_ids (used in app.py)
shopkeeper_shop_map = {}

# Starting ID counters
next_shop_id = 1001
next_item_id = 2001
next_order_id = 3001

def generate_shop_id():
    global next_shop_id
    shop_id = next_shop_id
    next_shop_id += 1
    return shop_id

def generate_item_id():
    global next_item_id
    item_id = next_item_id
    next_item_id += 1
    return item_id

def generate_order_id():
    global next_order_id
    order_id = next_order_id
    next_order_id += 1
    return order_id
