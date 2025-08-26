import gspread
from google.oauth2 import service_account
from google.cloud import firestore

# Paths to your credentials JSON files
GSHEETS_CREDENTIALS_FILE = '/Users/venkats/Desktop/Python_Projects/grocery-shopping-app/app/backend/grocery-credentials.json'
FIRESTORE_CREDENTIALS_FILE = '/Users/venkats/Desktop/Python_Projects/grocery-shopping-app/app/backend/serviceAccountKey.json'
SPREADSHEET_ID = '1atZmumA5MiMZmKaBtib2yeYRYOb0L-MmJJFPr_gVCiQ'

def main():
    # Authenticate with Google Sheets API
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds = service_account.Credentials.from_service_account_file(
        GSHEETS_CREDENTIALS_FILE, scopes=scopes)

    client_sheets = gspread.authorize(creds)

    # Open the spreadsheet and first sheet
    sheet = client_sheets.open_by_key(SPREADSHEET_ID).sheet1

    # Get all rows as a list of dictionaries
    records = sheet.get_all_records()

    print(f"Loaded {len(records)} records from Google Sheets.")

    # Authenticate Firestore
    firestore_creds = service_account.Credentials.from_service_account_file(
        FIRESTORE_CREDENTIALS_FILE)
    db = firestore.Client(credentials=firestore_creds, project=firestore_creds.project_id)

    collection_name = 'users'

    for record in records:
        username = record.get('username')
        if not username:
            print("Skipping a record with missing username...")
            continue

        # Optional: You can clean or validate fields here
        # For example, convert empty strings to None or trim spaces if needed

        # Use username as Firestore document ID for easy lookup
        doc_ref = db.collection(collection_name).document(username)
        doc_ref.set(record)
        print(f"Inserted/Updated user: {username}")

    print("Firestore migration completed successfully!")

if __name__ == "__main__":
    main()
