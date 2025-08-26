import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

# Scopes for Sheets + Drive
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Load credentials
creds = ServiceAccountCredentials.from_json_keyfile_name("grocery-credentials.json", scope)
client = gspread.authorize(creds)

# Open spreadsheet
spreadsheet = client.open("GroceryShop_Database")

# Sheets
shops_sheet = spreadsheet.worksheet("Shops")
items_sheet = spreadsheet.worksheet("Items")
orders_sheet = spreadsheet.worksheet("Orders")
users_sheet = spreadsheet.worksheet("Users")


def update_order_status_in_sheet(order_uuid, new_status, cancel_message=None):
    orders = orders_sheet.get_all_records()
    for idx, order in enumerate(orders, start=2):  # start=2 because row 1 is header
        if order.get("order_uuid") == order_uuid:

            # Update status (Column G = 7)
            orders_sheet.update_cell(idx, 7, new_status)

            # Update cancel_message (Column H = 8)
            if new_status.lower() == "cancelled" and cancel_message:
                orders_sheet.update_cell(idx, 8, cancel_message)

                # 🔄 Clear old cancel message if reverting from "cancelled"
            else:
                # 🔄 Clear old cancel message if reverting from "cancelled"
                orders_sheet.update_cell(idx, 8, "")
            return True


    return False


def get_user_by_credentials(username, password):
    users = users_sheet.get_all_records()


    for user in users:
        if str(user["username"]).strip() == str(username).strip() and str(user["password"]).strip() == str(password).strip():
            return user
    return None

def append_user_to_sheet(user_data):
    all_users = users_sheet.get_all_records()

    # Assign customer/shopkeeper ID
    if user_data["role"] == "shopkeeper":
        # Generate shopkeeper_id starting from 1000
        shopkeeper_id = 1000 + sum(1 for u in all_users if u["role"] == "shopkeeper")
        customer_id = ""
    else:
        # Generate customer_id starting from 2000
        customer_id = 2000 + sum(1 for u in all_users if u["role"] == "customer")
        shopkeeper_id = ""

    # Append to Google Sheet
    users_sheet.append_row([
        user_data["username"],
        user_data["password"],
        user_data["role"],
        str(customer_id),
        str(shopkeeper_id)
    ])

def user_exists(username):
    all_users = users_sheet.get_all_records()
    return any(u["username"] == username for u in all_users)


def add_shop(shop_data):
    existing = shops_sheet.get_all_values()
    shop_id = len(existing)  # assumes header is row 1
    new_row = [str(shop_id), shop_data['name'], str(shop_data['shopkeeper_id'])]
    shops_sheet.append_row(new_row)
    return shop_id


def add_items(shop_id, items):
    for item in items:
        name = item.get('name', '')
        price = item.get('price', '')
        stock = item.get('stock', '')
        new_row = [str(shop_id), name, str(price), str(stock)]
        items_sheet.append_row(new_row)



#
# import gspread
# from datetime import datetime
# from oauth2client.service_account import ServiceAccountCredentials
#
# # Scopes for Sheets + Drive
# scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
#
# # Start with None (lazy load later)
# service = None
# client = None
# spreadsheet = None
# shops_sheet = None
# items_sheet = None
# orders_sheet = None
# users_sheet = None
#
#
# def init_sheets():
#     """Initializes the Google Sheets connection only when needed."""
#     global service, client, spreadsheet, shops_sheet, items_sheet, orders_sheet, users_sheet
#
#     if shops_sheet is not None:
#         return  # Already initialized
#
#     creds = ServiceAccountCredentials.from_json_keyfile_name("grocery-credentials.json", scope)
#     client = gspread.authorize(creds)
#     spreadsheet = client.open("GroceryShop_Database")
#
#     # Assign to globals so old imports still work
#     globals()["shops_sheet"] = spreadsheet.worksheet("Shops")
#     globals()["items_sheet"] = spreadsheet.worksheet("Items")
#     globals()["orders_sheet"] = spreadsheet.worksheet("Orders")
#     globals()["users_sheet"] = spreadsheet.worksheet("Users")
#
#
# def update_order_status_in_sheet(order_uuid, new_status, cancel_message=None):
#     init_sheets()
#     orders = orders_sheet.get_all_records()
#     for idx, order in enumerate(orders, start=2):  # start=2 because row 1 is header
#         if order.get("order_uuid") == order_uuid:
#             orders_sheet.update_cell(idx, 7, new_status)
#             if new_status.lower() == "cancelled" and cancel_message:
#                 orders_sheet.update_cell(idx, 8, cancel_message)
#             else:
#                 orders_sheet.update_cell(idx, 8, "")
#             return True
#     return False
#
#
# def get_user_by_credentials(username, password):
#     init_sheets()
#     users = users_sheet.get_all_records()
#     for user in users:
#         if str(user["username"]).strip() == str(username).strip() and str(user["password"]).strip() == str(password).strip():
#             return user
#     return None
#
#
# def append_user_to_sheet(user_data):
#     init_sheets()
#     all_users = users_sheet.get_all_records()
#     if user_data["role"] == "shopkeeper":
#         shopkeeper_id = 1000 + sum(1 for u in all_users if u["role"] == "shopkeeper")
#         customer_id = ""
#     else:
#         customer_id = 2000 + sum(1 for u in all_users if u["role"] == "customer")
#         shopkeeper_id = ""
#     users_sheet.append_row([
#         user_data["username"],
#         user_data["password"],
#         user_data["role"],
#         str(customer_id),
#         str(shopkeeper_id)
#     ])
#
#
# def user_exists(username):
#     init_sheets()
#     all_users = users_sheet.get_all_records()
#     return any(u["username"] == username for u in all_users)
#
#
# def add_shop(shop_data):
#     init_sheets()
#     existing = shops_sheet.get_all_values()
#     shop_id = len(existing)  # assumes header is row 1
#     new_row = [str(shop_id), shop_data['name'], str(shop_data['shopkeeper_id'])]
#     shops_sheet.append_row(new_row)
#     return shop_id
#
#
# def add_items(shop_id, items):
#     init_sheets()
#     for item in items:
#         name = item.get('name', '')
#         price = item.get('price', '')
#         stock = item.get('stock', '')
#         new_row = [str(shop_id), name, str(price), str(stock)]
#         items_sheet.append_row(new_row)
