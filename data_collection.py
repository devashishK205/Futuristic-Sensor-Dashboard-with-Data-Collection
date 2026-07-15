"""
data_collection.py – Fetches historical sensor data from Firebase
using the REST API with email/password authentication.
No service account key required.
"""

import requests
import pandas as pd
import numpy as np
import time
import os

# ---------- Firebase config (from your web app) ----------
API_KEY = "AIzaSyDRK3k7DJ1NmGATWMjcKUmzYiVcxYDsOIQ"
DATABASE_URL = "https://project-67b08-default-rtdb.firebaseio.com"
USER_EMAIL = "sb284160@gmail.com"
USER_PASSWORD = "Password@1"

# ---------- Device definitions ----------
DEVICES = {
    'dht11': {
        'path': '/machines/machine_01/devices/dht11/history',
        'columns': ['temperature', 'humidity'],
        'extra': ['datetime']
    },
    'voltage': {
        'path': '/machines/machine_01/devices/voltage/history',
        'columns': ['value'],
        'rename': 'voltage',
        'extra': ['datetime']
    },
    'current': {
        'path': '/machines/machine_01/devices/current/history',
        'columns': ['value'],
        'rename': 'current',
        'extra': ['datetime']
    },
    'mpu6050': {
        'path': '/machines/machine_01/devices/mpu6050/history',
        'columns': ['value'],
        'rename': 'vibration',
        'extra': ['datetime']
    }
}

# ---------- Firebase Authentication ----------
def get_id_token():
    """Sign in with email/password and return the ID token."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
    payload = {
        "email": USER_EMAIL,
        "password": USER_PASSWORD,
        "returnSecureToken": True
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data['idToken']
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        if 'error' in response.json():
            print(f"   Error details: {response.json()['error']['message']}")
        return None

# ---------- Fetch data from Firebase REST API ----------
def fetch_path(path, token):
    """Fetch data from a given Firebase path with authentication."""
    url = f"{DATABASE_URL}{path}.json?auth={token}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Error fetching {path}: {e}")
        return None

def fetch_history(device_name, token):
    """Fetch history entries for a device and return a DataFrame."""
    ref_path = DEVICES[device_name]['path']
    data = fetch_path(ref_path, token)
    if data is None:
        print(f"   ⚠️ No data at {ref_path}")
        return pd.DataFrame()
    print(f"   ✅ Raw data has {len(data)} entries")
    rows = []
    for ts_str, values in data.items():
        try:
            timestamp_ms = int(ts_str)
        except ValueError:
            continue
        row = {'timestamp_ms': timestamp_ms}
        for col in DEVICES[device_name]['columns']:
            row[col] = values.get(col, np.nan)
        for extra in DEVICES[device_name].get('extra', []):
            row[extra] = values.get(extra, None)
        rows.append(row)
    df = pd.DataFrame(rows)
    if 'rename' in DEVICES[device_name]:
        new_name = DEVICES[device_name]['rename']
        if 'value' in df.columns:
            df.rename(columns={'value': new_name}, inplace=True)
    df['timestamp'] = pd.to_datetime(df['timestamp_ms'], unit='ms')
    if 'datetime' not in df.columns:
        df['datetime'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    print(f"   Sample first 2 rows:\n{df.head(2).to_string()}\n")
    return df

def merge_all_data(token):
    """Merge data from all devices."""
    dfs = []
    for device in DEVICES:
        print(f"\n📌 Fetching {device}...")
        df = fetch_history(device, token)
        if not df.empty:
            print(f"   ✓ {len(df)} records fetched for {device}")
            dfs.append(df)
        else:
            print(f"   ✗ No records for {device}")
    if not dfs:
        print("No data fetched!")
        return pd.DataFrame()

    merged = dfs[0]
    for i in range(1, len(dfs)):
        right = dfs[i]
        print(f"\n🔄 Merging with device {i} ({right.shape[0]} rows)...")
        merged = pd.merge(merged, right, on='timestamp_ms', how='outer', suffixes=('', f'_right_{i}'))
        for col in list(merged.columns):
            if col.endswith('_y') or '_right_' in col:
                if col in ['timestamp_y', 'datetime_y']:
                    merged.drop(columns=[col], inplace=True)
        if 'datetime' not in merged.columns:
            dt_cols = [c for c in merged.columns if c.startswith('datetime')]
            if dt_cols:
                merged['datetime'] = merged[dt_cols[0]]
        print(f"   After merge: {merged.shape[0]} rows")

    feature_cols = ['timestamp_ms', 'timestamp', 'datetime',
                    'temperature', 'humidity', 'voltage', 'current', 'vibration']
    for col in feature_cols:
        if col not in merged.columns:
            merged[col] = np.nan
    merged = merged[feature_cols]
    merged = merged.sort_values('timestamp_ms').reset_index(drop=True)
    return merged

def main():
    print("🔑 Getting Firebase authentication token...")
    token = get_id_token()
    if token is None:
        print("❌ Could not authenticate. Check your email/password.")
        return

    print("✅ Authentication successful.")
    print("Collecting ALL historical data from Firebase (full outer join)...")
    df = merge_all_data(token)
    if df.empty:
        print("No data collected. Exiting.")
        return

    csv_file = 'dataset.csv'
    df.to_csv(csv_file, index=False)
    print(f"\n✅ Dataset saved to {csv_file} with {len(df)} records.")
    print("Columns:", df.columns.tolist())
    print("Rows with no missing data:", df.dropna().shape[0])
    print("Rows with at least one missing value:", df.shape[0] - df.dropna().shape[0])

if __name__ == '__main__':
    main()