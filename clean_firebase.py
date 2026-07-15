"""
clean_firebase.py – Delete all data from Firebase Realtime Database.
Use with extreme caution – this operation is irreversible!
"""

import firebase_admin
from firebase_admin import credentials, db
import sys

# ---------- Firebase setup ----------
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://project-67b08-default-rtdb.firebaseio.com/'
    })
    print("✅ Firebase initialized.")
except Exception as e:
    print("❌ Firebase init error:", e)
    sys.exit(1)

# ---------- Choose what to delete ----------
# Option 1: Delete everything under a specific path (e.g., '/machines')
# Set this to None to delete the entire database (root).
PATH_TO_DELETE = "/machines"  # Change to "/" for root deletion


def confirm_deletion(path):
    """Ask for user confirmation before deleting."""
    print("\n⚠️  WARNING: This will permanently delete all data at:")
    print(f"   {path if path else 'ROOT (entire database)'}")
    print("This action is IRREVERSIBLE!")
    response = input("Type 'YES' to confirm deletion: ")
    return response.strip().upper() == "YES"


def delete_data():
    if PATH_TO_DELETE is None or PATH_TO_DELETE == "":
        ref = db.reference()
    else:
        ref = db.reference(PATH_TO_DELETE)

    if not confirm_deletion(PATH_TO_DELETE):
        print("❌ Deletion cancelled.")
        return

    try:
        ref.delete()
        print(f"✅ Data at '{PATH_TO_DELETE if PATH_TO_DELETE else 'ROOT'}' deleted successfully.")
    except Exception as e:
        print(f"❌ Error during deletion: {e}")


if __name__ == "__main__":
    delete_data()