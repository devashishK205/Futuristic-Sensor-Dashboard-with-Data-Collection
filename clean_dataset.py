"""
clean_dataset.py – Cleans dataset.csv by:
- Ensuring all five sensor columns exist
- Forward‑filling missing values within each column
- Replacing any remaining NaN with 0
- Dropping timestamp columns (not needed for model)
- Saving back to dataset.csv
"""

import pandas as pd
import numpy as np

# The five sensor columns we need for training
SENSOR_COLS = ['temperature', 'humidity', 'voltage', 'current', 'vibration']

def clean_dataset():
    # Load the raw data
    df = pd.read_csv('dataset.csv')
    print(f"Original shape: {df.shape}")
    print("Original columns:", df.columns.tolist())

    # 1. Ensure all sensor columns exist (add missing ones with NaN)
    for col in SENSOR_COLS:
        if col not in df.columns:
            df[col] = np.nan
            print(f"Added missing column: {col}")

    # 2. Sort by timestamp if available
    if 'timestamp_ms' in df.columns:
        df = df.sort_values('timestamp_ms').reset_index(drop=True)
    elif 'timestamp' in df.columns:
        df = df.sort_values('timestamp').reset_index(drop=True)

    # 3. Forward‑fill each sensor column (carry last known value forward)
    df[SENSOR_COLS] = df[SENSOR_COLS].ffill()

    # 4. For columns that are still all NaN (no data at all), fill with 0
    for col in SENSOR_COLS:
        if df[col].isna().all():
            df[col] = 0
            print(f"Column {col} had no data – filled with 0.")

    # 5. Drop rows that are still empty (should be none, but just in case)
    df = df.dropna(subset=SENSOR_COLS, how='any')

    # 6. Keep only the sensor columns for training
    df_clean = df[SENSOR_COLS].copy()

    # 7. Save back to dataset.csv
    df_clean.to_csv('dataset.csv', index=False)
    print(f"\n✅ Cleaned dataset saved to dataset.csv")
    print(f"Final shape: {df_clean.shape}")
    print("Columns:", df_clean.columns.tolist())
    print("\nFirst few rows:")
    print(df_clean.head())
    print("\nMissing values after cleaning:")
    print(df_clean.isna().sum())

if __name__ == '__main__':
    clean_dataset()