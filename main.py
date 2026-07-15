#!/usr/bin/env python3
"""
Futuristic Sensor Dashboard with Data Collection
================================================
- Collect historical data from Firebase (REST API)
- Build anomaly detection model (Tukey's fences + Mahalanobis)
- Real‑time monitoring with animated gauges, alerts, email
- All in one file – no external HTML/CSS/JS.
"""

import math
import threading
import time
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests
from flask import Flask, jsonify, render_template_string, request
from scipy.spatial.distance import mahalanobis
from scipy.stats import chi2

# ---------- Firebase REST config ----------
API_KEY = "AIzaSyDRK3k7DJ1NmGATWMjcKUmzYiVcxYDsOIQ"
DATABASE_URL = "https://project-67b08-default-rtdb.firebaseio.com"
USER_EMAIL = "sb284160@gmail.com"
USER_PASSWORD = "Password@1"

# ---------- Device definitions for data collection ----------
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

# ---------- Authentication helper ----------
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
        return None

# ---------- Data collection function ----------
def collect_historical_data():
    """Fetch all historical data from Firebase and save to dataset.csv."""
    token = get_id_token()
    if token is None:
        return False, "Authentication failed"

    def fetch_path(path):
        url = f"{DATABASE_URL}{path}.json?auth={token}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Fetch error: {e}")
            return None

    def fetch_history(device_name):
        ref_path = DEVICES[device_name]['path']
        data = fetch_path(ref_path)
        if data is None:
            return pd.DataFrame()
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
        return df

    dfs = []
    for device in DEVICES:
        print(f"Fetching {device}...")
        df = fetch_history(device)
        if not df.empty:
            dfs.append(df)

    if not dfs:
        return False, "No data found"

    merged = dfs[0]
    for i in range(1, len(dfs)):
        right = dfs[i]
        merged = pd.merge(merged, right, on='timestamp_ms', how='outer', suffixes=('', f'_right_{i}'))
        for col in list(merged.columns):
            if col.endswith('_y') or '_right_' in col:
                if col in ['timestamp_y', 'datetime_y']:
                    merged.drop(columns=[col], inplace=True)
        if 'datetime' not in merged.columns:
            dt_cols = [c for c in merged.columns if c.startswith('datetime')]
            if dt_cols:
                merged['datetime'] = merged[dt_cols[0]]

    feature_cols = ['timestamp_ms', 'timestamp', 'datetime',
                    'temperature', 'humidity', 'voltage', 'current', 'vibration']
    for col in feature_cols:
        if col not in merged.columns:
            merged[col] = np.nan
    merged = merged[feature_cols]
    merged = merged.sort_values('timestamp_ms').reset_index(drop=True)

    merged.to_csv('dataset.csv', index=False)
    return True, f"Saved {len(merged)} records to dataset.csv"

# ---------- Model builder ----------
def build_model_from_dataset(csv_file='dataset.csv'):
    """Build anomaly detection model from dataset."""
    try:
        df = pd.read_csv(csv_file)
        required = ['temperature', 'humidity', 'voltage', 'current', 'vibration']
        for col in required:
            if col not in df.columns:
                df[col] = 0
        df = df[required]
        df = df[(df != 0).any(axis=1)]
        if df.empty:
            raise ValueError("Dataset empty after cleaning.")

        sensor_stats = {}
        for col in required:
            series = df[col].dropna()
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            # Clamp to physical limits
            if col == 'temperature':
                lower, upper = max(lower, 0), min(upper, 60)
            elif col == 'humidity':
                lower, upper = max(lower, 0), min(upper, 100)
            elif col == 'voltage':
                lower, upper = max(lower, 100), min(upper, 300)
            elif col == 'current':
                lower, upper = max(lower, -5), min(upper, 25)
            elif col == 'vibration':
                lower, upper = max(lower, 0), min(upper, 5)

            sensor_stats[col] = {
                'mean': series.mean(),
                'std': series.std(),
                'q1': q1,
                'q3': q3,
                'iqr': iqr,
                'lower': lower,
                'upper': upper
            }

        data_matrix = df[required].values
        mean_vec = data_matrix.mean(axis=0)
        cov_matrix = np.cov(data_matrix, rowvar=False)
        cov_matrix += np.eye(cov_matrix.shape[0]) * 1e-6

        model = {
            'sensor_stats': sensor_stats,
            'mean_vec': mean_vec,
            'cov_matrix': cov_matrix,
            'features': required,
            'chi2_threshold': chi2.ppf(0.99, df=len(required))
        }
        return model
    except Exception as e:
        print(f"Model build error: {e}. Using fallback fixed ranges.")
        fixed_ranges = {
            'temperature': (20, 40),
            'humidity': (30, 80),
            'voltage': (210, 250),
            'current': (0, 15),
            'vibration': (0, 2.0)
        }
        sensor_stats = {}
        for col in fixed_ranges:
            sensor_stats[col] = {
                'mean': (fixed_ranges[col][0] + fixed_ranges[col][1]) / 2,
                'std': (fixed_ranges[col][1] - fixed_ranges[col][0]) / 4,
                'q1': fixed_ranges[col][0],
                'q3': fixed_ranges[col][1],
                'iqr': fixed_ranges[col][1] - fixed_ranges[col][0],
                'lower': fixed_ranges[col][0],
                'upper': fixed_ranges[col][1]
            }
        mean_vec = np.array([sensor_stats[c]['mean'] for c in fixed_ranges])
        cov_matrix = np.eye(len(fixed_ranges)) * 0.1
        return {
            'sensor_stats': sensor_stats,
            'mean_vec': mean_vec,
            'cov_matrix': cov_matrix,
            'features': list(fixed_ranges.keys()),
            'chi2_threshold': chi2.ppf(0.99, df=len(fixed_ranges))
        }

# ---------- Global model ----------
MODEL = build_model_from_dataset('dataset.csv')

SENSORS = {
    'temperature': {'label': 'Temperature', 'unit': '°C', 'fmt': '{:.1f}', 'firebase_key': 'dht'},
    'humidity':    {'label': 'Humidity',    'unit': '%',  'fmt': '{:.1f}', 'firebase_key': 'dht'},
    'voltage':     {'label': 'Voltage',     'unit': 'V',  'fmt': '{:.1f}', 'firebase_key': 'voltage'},
    'current':     {'label': 'Current',     'unit': 'A',  'fmt': '{:.2f}', 'firebase_key': 'current'},
    'vibration':   {'label': 'Vibration',   'unit': 'g',  'fmt': '{:.3f}', 'firebase_key': 'mpu'}
}

# ---------- Flask app ----------
app = Flask(__name__)

# Global data cache
latest_data = {
    'values': {k: np.nan for k in SENSORS},
    'timestamps': {k: None for k in SENSORS},
    'datetimes': {k: None for k in SENSORS},
    'status': {k: False for k in ['dht','voltage','current','mpu']},
    'per_sensor_alerts': {},
    'global_anomaly': False,
    'anomaly_score': 0.0,
    'online': {k: False for k in SENSORS},
    'stale': {k: False for k in SENSORS},
    'in_alert': {k: False for k in SENSORS},
    'last_update': None
}
data_lock = threading.Lock()

# ---------- Email config (optional) ----------
EMAIL_ENABLED = False
if 'EMAIL_USER' in os.environ and 'EMAIL_PASSWORD' in os.environ and 'EMAIL_TO' in os.environ:
    EMAIL_ENABLED = True
    EMAIL_USER = os.environ['EMAIL_USER']
    EMAIL_PASSWORD = os.environ['EMAIL_PASSWORD']
    EMAIL_TO = os.environ['EMAIL_TO']
    print("Email alerts enabled.")
else:
    print("Email alerts disabled (set EMAIL_USER, EMAIL_PASSWORD, EMAIL_TO env vars).")

sent_alerts = set()

def send_alert_email(sensor, message, value=None):
    if not EMAIL_ENABLED:
        return
    try:
        subject = f"⚠️ Sensor Alert: {sensor}"
        body = f"""
Sensor: {sensor}
Alert: {message}
Value: {value if value is not None else 'N/A'}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Email sent for {sensor}")
    except Exception as e:
        print(f"Email error: {e}")

# ---------- Firebase live fetch (REST) ----------
def fetch_live_data():
    token = get_id_token()
    if token is None:
        return {k: np.nan for k in SENSORS}, {k: None for k in SENSORS}, {k: None for k in SENSORS}, {k: False for k in ['dht','voltage','current','mpu']}

    data = {k: np.nan for k in SENSORS}
    timestamps = {k: None for k in SENSORS}
    datetimes = {k: None for k in SENSORS}
    status = {k: False for k in ['dht','voltage','current','mpu']}

    def get_path(path):
        url = f"{DATABASE_URL}{path}.json?auth={token}"
        try:
            r = requests.get(url)
            r.raise_for_status()
            return r.json()
        except:
            return None

    dht = get_path('/machines/machine_01/devices/dht11/latest')
    if dht:
        data['temperature'] = dht.get('temperature', np.nan)
        data['humidity'] = dht.get('humidity', np.nan)
        timestamps['temperature'] = dht.get('timestamp', None)
        datetimes['temperature'] = dht.get('datetime', None)
        timestamps['humidity'] = dht.get('timestamp', None)
        datetimes['humidity'] = dht.get('datetime', None)
        status['dht'] = True

    vol = get_path('/machines/machine_01/devices/voltage/latest')
    if vol:
        data['voltage'] = vol.get('value', np.nan)
        timestamps['voltage'] = vol.get('timestamp', None)
        datetimes['voltage'] = vol.get('datetime', None)
        status['voltage'] = True

    cur = get_path('/machines/machine_01/devices/current/latest')
    if cur:
        data['current'] = cur.get('value', np.nan)
        timestamps['current'] = cur.get('timestamp', None)
        datetimes['current'] = cur.get('datetime', None)
        status['current'] = True

    mpu = get_path('/machines/machine_01/devices/mpu6050/latest')
    if mpu:
        data['vibration'] = mpu.get('value', np.nan)
        timestamps['vibration'] = mpu.get('timestamp', None)
        datetimes['vibration'] = mpu.get('datetime', None)
        status['mpu'] = True

    return data, timestamps, datetimes, status

# ---------- Anomaly detection ----------
def detect_anomalies(values):
    per_sensor = {}
    sensor_stats = MODEL['sensor_stats']
    features = MODEL['features']

    for key in features:
        val = values.get(key, np.nan)
        if pd.isna(val):
            continue
        lower = sensor_stats[key]['lower']
        upper = sensor_stats[key]['upper']
        if val < lower:
            per_sensor[key] = f"{key} too low ({val:.2f} < {lower:.2f})"
        elif val > upper:
            per_sensor[key] = f"{key} too high ({val:.2f} > {upper:.2f})"

    global_anomaly = False
    anomaly_score = 0.0
    vec = []
    valid = True
    for f in features:
        v = values.get(f, np.nan)
        if pd.isna(v):
            valid = False
            break
        vec.append(v)
    if valid:
        vec = np.array(vec)
        mean_vec = MODEL['mean_vec']
        cov_inv = np.linalg.inv(MODEL['cov_matrix'])
        dist = mahalanobis(vec, mean_vec, cov_inv)
        anomaly_score = dist
        if dist > MODEL['chi2_threshold']:
            global_anomaly = True
            if not per_sensor:
                per_sensor['system'] = f"Multivariate anomaly (distance={dist:.2f})"

    return per_sensor, global_anomaly, anomaly_score

# ---------- Background updater ----------
def background_updater():
    while True:
        try:
            values, timestamps, datetimes, status = fetch_live_data()
            per_sensor_alerts, global_anomaly, anomaly_score = detect_anomalies(values)
            alert_keys = set(per_sensor_alerts.keys())

            valid_timestamps = [ts for ts in timestamps.values() if ts is not None and not pd.isna(ts)]
            max_ts = max(valid_timestamps) if valid_timestamps else None

            online = {}
            stale = {}
            for key in SENSORS:
                ts = timestamps.get(key, None)
                raw_online = False
                fk = SENSORS[key]['firebase_key']
                if fk == 'dht':
                    raw_online = status['dht']
                elif fk == 'voltage':
                    raw_online = status['voltage']
                elif fk == 'current':
                    raw_online = status['current']
                elif fk == 'mpu':
                    raw_online = status['mpu']

                if raw_online and ts is not None and not pd.isna(ts) and max_ts is not None:
                    age = max_ts - ts
                    if age <= 5000:
                        online[key] = True
                        stale[key] = False
                    else:
                        online[key] = False
                        stale[key] = True
                else:
                    online[key] = False
                    stale[key] = False

            with data_lock:
                latest_data['values'] = values
                latest_data['timestamps'] = timestamps
                latest_data['datetimes'] = datetimes
                latest_data['status'] = status
                latest_data['per_sensor_alerts'] = per_sensor_alerts
                latest_data['global_anomaly'] = global_anomaly
                latest_data['anomaly_score'] = anomaly_score
                latest_data['online'] = online
                latest_data['stale'] = stale
                latest_data['in_alert'] = {k: (k in alert_keys or global_anomaly) for k in SENSORS}
                latest_data['last_update'] = datetime.now().isoformat()

            # Email alerts
            current_alerts = set()
            for sensor, msg in per_sensor_alerts.items():
                if sensor == 'system':
                    continue
                key = (sensor, msg)
                current_alerts.add(key)
                if key not in sent_alerts:
                    val = values.get(sensor, None)
                    send_alert_email(sensor, msg, val)
                    sent_alerts.add(key)
            if global_anomaly:
                global_key = ('global', str(anomaly_score))
                current_alerts.add(global_key)
                if global_key not in sent_alerts:
                    send_alert_email('System', f'Global multivariate anomaly (score={anomaly_score:.2f})')
                    sent_alerts.add(global_key)

            to_remove = [k for k in sent_alerts if k not in current_alerts]
            for k in to_remove:
                sent_alerts.remove(k)

        except Exception as e:
            print("Background updater error:", e)
        time.sleep(2)

thread = threading.Thread(target=background_updater, daemon=True)
thread.start()

# ---------- Routes ----------
@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def api_data():
    with data_lock:
        response = {
            'values': {},
            'timestamps': {},
            'datetimes': {},
            'online': {},
            'stale': {},
            'in_alert': {},
            'ranges': {},
            'fmt': {},
            'units': {},
            'labels': {},
            'per_sensor_alerts': latest_data['per_sensor_alerts'],
            'global_anomaly': latest_data['global_anomaly'],
            'anomaly_score': latest_data['anomaly_score'],
            'last_update': latest_data.get('last_update')
        }
        for key in SENSORS:
            val = latest_data['values'].get(key, np.nan)
            response['values'][key] = None if pd.isna(val) else float(val)
            response['timestamps'][key] = latest_data['timestamps'].get(key)
            response['datetimes'][key] = latest_data['datetimes'].get(key)
            response['online'][key] = latest_data['online'].get(key, False)
            response['stale'][key] = latest_data['stale'].get(key, False)
            response['in_alert'][key] = latest_data['in_alert'].get(key, False)
            stats = MODEL['sensor_stats'].get(key, {'lower': 0, 'upper': 1})
            response['ranges'][key] = (stats['lower'], stats['upper'])
            response['fmt'][key] = SENSORS[key]['fmt']
            response['units'][key] = SENSORS[key]['unit']
            response['labels'][key] = SENSORS[key]['label']
        return jsonify(response)

@app.route('/api/collect', methods=['POST'])
def collect_data():
    """Trigger historical data collection and model rebuild."""
    success, message = collect_historical_data()
    if success:
        global MODEL
        MODEL = build_model_from_dataset('dataset.csv')
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 500

# ---------- HTML Template with "Refresh Dataset" button ----------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>✨ Sensor Dashboard</title>
    <style>
        /* (same as before, plus a new button style) */
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #f0f4ff, #e6edf9);
            font-family: 'Inter', 'Segoe UI', Roboto, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
            position: relative;
            overflow-x: hidden;
        }
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: radial-gradient(circle at 20% 50%, rgba(100,200,255,0.08) 0%, transparent 60%),
                        radial-gradient(circle at 80% 50%, rgba(100,200,255,0.05) 0%, transparent 60%);
            z-index: -1;
            animation: bgShift 20s ease-in-out infinite alternate;
        }
        @keyframes bgShift {
            0% { transform: scale(1) rotate(0deg); }
            100% { transform: scale(1.2) rotate(5deg); }
        }
        .header {
            width: 100%;
            max-width: 1200px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 24px;
            background: rgba(255,255,255,0.6);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.06);
            border: 1px solid rgba(255,255,255,0.8);
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 10px;
        }
        .logo-area {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .logo-icon { font-size: 2.2rem; animation: float 3s ease-in-out infinite; }
        @keyframes float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
        .logo-text {
            font-size: 1.6rem;
            font-weight: 700;
            background: linear-gradient(135deg, #0077be, #00a8cc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header-right {
            display: flex;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
        }
        .update-time { color: #2c3e50; font-weight: 500; font-size: 0.9rem; }
        .btn-refresh {
            background: #0077be;
            color: #fff;
            border: none;
            padding: 6px 16px;
            border-radius: 20px;
            font-weight: 600;
            font-size: 0.8rem;
            cursor: pointer;
            transition: background 0.2s, transform 0.2s;
        }
        .btn-refresh:hover { background: #005f8a; transform: scale(1.02); }
        .btn-refresh:active { transform: scale(0.95); }
        .btn-refresh:disabled { opacity: 0.6; cursor: not-allowed; }
        .anomaly-badge {
            background: #ff6b6b;
            color: #fff;
            padding: 2px 14px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
            box-shadow: 0 0 20px rgba(255,107,107,0.3);
            animation: glowBadge 1.2s infinite alternate;
            display: inline-block;
        }
        @keyframes glowBadge {
            0% { box-shadow: 0 0 8px rgba(255,107,107,0.3); }
            100% { box-shadow: 0 0 24px rgba(255,107,107,0.7); }
        }
        .status-text { font-size: 0.75rem; color: #7f8c8d; }

        .dashboard {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 24px;
            max-width: 1200px;
            width: 100%;
        }
        .card {
            background: rgba(255,255,255,0.7);
            backdrop-filter: blur(8px);
            border-radius: 24px;
            border: 1px solid rgba(255,255,255,0.9);
            padding: 20px 18px 18px;
            position: relative;
            transition: all 0.4s ease;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 280px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.04);
        }
        .card.alert {
            border-color: #ff6b6b;
            box-shadow: 0 0 30px rgba(255,107,107,0.3);
            animation: alertGlow 1.2s infinite alternate;
        }
        @keyframes alertGlow {
            0% { box-shadow: 0 0 20px rgba(255,107,107,0.2); }
            100% { box-shadow: 0 0 50px rgba(255,107,107,0.6); }
        }
        .card.stale { border-color: #feca57; box-shadow: 0 0 20px rgba(254,202,87,0.2); }
        .card.offline { opacity: 0.5; border-color: #bdc3c7; }
        .dot {
            position: absolute;
            top: 16px;
            left: 20px;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            display: inline-block;
            transition: background 0.2s;
        }
        .dot.online { background: #00b894; box-shadow: 0 0 12px #00b894; }
        .dot.stale { background: #feca57; box-shadow: 0 0 12px #feca57; animation: blinkAmber 1s infinite alternate; }
        @keyframes blinkAmber { 0% { opacity: 0.5; } 100% { opacity: 1; } }
        .dot.offline { background: #bdc3c7; animation: blinkOffline 1.2s infinite; }
        @keyframes blinkOffline { 0%,100% { opacity: 1; } 50% { opacity: 0.2; } }

        .card-title {
            font-size: 1rem;
            font-weight: 600;
            color: #2c3e50;
            letter-spacing: 0.3px;
            margin-left: 28px;
            align-self: flex-start;
            text-transform: uppercase;
        }
        .value {
            font-size: 2.6rem;
            font-weight: 700;
            font-family: 'Roboto Mono', monospace;
            color: #0077be;
            letter-spacing: 1px;
        }
        .value.alert { color: #ff6b6b; }
        .value.stale { color: #feca57; }
        .value.offline { color: #95a5a6; }
        .unit { font-size: 1rem; color: #7f8c8d; margin-left: 4px; }
        .range-text { font-size: 0.7rem; color: #bdc3c7; margin-top: 2px; }
        .status {
            font-size: 0.85rem;
            font-weight: 600;
            margin-top: 4px;
        }
        .status.ideal { color: #00b894; }
        .status.alert { color: #ff6b6b; }
        .status.stale { color: #feca57; }
        .status.offline { color: #95a5a6; }
        .timestamp {
            font-size: 0.7rem;
            color: #bdc3c7;
            margin-top: 2px;
        }
        .gauge-container {
            margin-top: 8px;
            width: 100%;
            display: flex;
            justify-content: center;
        }
        canvas { width: 140px; height: 80px; display: block; }

        .footer {
            margin-top: 40px;
            padding: 16px 0;
            border-top: 1px solid rgba(0,0,0,0.05);
            width: 100%;
            max-width: 1200px;
            text-align: center;
            color: #95a5a6;
            font-size: 0.8rem;
        }
        @media (max-width: 820px) {
            .dashboard { grid-template-columns: repeat(2, 1fr); gap: 18px; }
            .header { flex-direction: column; align-items: flex-start; }
            .header-right { align-items: flex-start; width: 100%; }
        }
        @media (max-width: 540px) {
            .dashboard { grid-template-columns: 1fr; }
            canvas { width: 120px; height: 70px; }
            .value { font-size: 2rem; }
        }
    </style>
</head>
<body>
    <header class="header">
        <div class="logo-area">
            <span class="logo-icon">⚡</span>
            <span class="logo-text">SENSOR DASH</span>
        </div>
        <div class="header-right">
            <div class="update-time" id="globalUpdate">Updating...</div>
            <div id="globalAnomalyBadge" style="display:none;" class="anomaly-badge">⚠ SYSTEM ANOMALY</div>
            <button class="btn-refresh" id="refreshBtn" onclick="refreshDataset()">⟳ Refresh Dataset</button>
            <div class="status-text">Live • Model‑based</div>
        </div>
    </header>

    <div class="dashboard" id="dashboard"></div>

    <footer class="footer">
        &copy; 2026 Sensor Systems &bull; Data refreshed every 2s &bull; Anomaly detection: Tukey's fences + Mahalanobis
    </footer>

    <script>
        // ---------- Audio beep ----------
        function playBeep(frequency=800, duration=200, volume=0.3) {
            try {
                const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                const oscillator = audioCtx.createOscillator();
                const gainNode = audioCtx.createGain();
                oscillator.type = 'sine';
                oscillator.frequency.value = frequency;
                gainNode.gain.value = volume;
                oscillator.connect(gainNode);
                gainNode.connect(audioCtx.destination);
                oscillator.start();
                oscillator.stop(audioCtx.currentTime + duration / 1000);
            } catch (e) {}
        }

        // ---------- Refresh dataset ----------
        async function refreshDataset() {
            const btn = document.getElementById('refreshBtn');
            btn.disabled = true;
            btn.textContent = '⏳ Collecting...';
            try {
                const resp = await fetch('/api/collect', { method: 'POST' });
                const data = await resp.json();
                if (data.success) {
                    alert('✅ Dataset refreshed: ' + data.message);
                } else {
                    alert('❌ Error: ' + data.message);
                }
            } catch (e) {
                alert('❌ Network error');
            }
            btn.disabled = false;
            btn.textContent = '⟳ Refresh Dataset';
        }

        // ---------- Dashboard setup ----------
        const SENSOR_KEYS = ['temperature', 'humidity', 'voltage', 'current', 'vibration'];
        const dashboard = document.getElementById('dashboard');
        const cardElements = {};

        function createCard(key) {
            const card = document.createElement('div');
            card.className = 'card';
            card.id = `card-${key}`;

            const dot = document.createElement('span');
            dot.className = 'dot offline';
            dot.id = `dot-${key}`;
            card.appendChild(dot);

            const title = document.createElement('div');
            title.className = 'card-title';
            title.id = `label-${key}`;
            title.textContent = key.charAt(0).toUpperCase() + key.slice(1);
            card.appendChild(title);

            const valueWrapper = document.createElement('div');
            valueWrapper.style.display = 'flex';
            valueWrapper.style.alignItems = 'baseline';
            valueWrapper.style.gap = '4px';

            const value = document.createElement('span');
            value.className = 'value offline';
            value.id = `value-${key}`;
            value.textContent = '---';
            valueWrapper.appendChild(value);

            const unit = document.createElement('span');
            unit.className = 'unit';
            unit.id = `unit-${key}`;
            unit.textContent = '';
            valueWrapper.appendChild(unit);

            card.appendChild(valueWrapper);

            const range = document.createElement('div');
            range.className = 'range-text';
            range.id = `range-${key}`;
            range.textContent = '';
            card.appendChild(range);

            const status = document.createElement('div');
            status.className = 'status offline';
            status.id = `status-${key}`;
            status.textContent = '⏳ waiting';
            card.appendChild(status);

            const ts = document.createElement('div');
            ts.className = 'timestamp';
            ts.id = `ts-${key}`;
            ts.textContent = 'Last: —';
            card.appendChild(ts);

            const gaugeDiv = document.createElement('div');
            gaugeDiv.className = 'gauge-container';
            const canvas = document.createElement('canvas');
            canvas.width = 140;
            canvas.height = 80;
            canvas.id = `gauge-${key}`;
            gaugeDiv.appendChild(canvas);
            card.appendChild(gaugeDiv);

            dashboard.appendChild(card);
            cardElements[key] = { card, dot, value, unit, range, status, ts, canvas };
        }

        SENSOR_KEYS.forEach(createCard);

        // ---------- Gauge drawing ----------
        function drawGauge(ctx, cx, cy, radius, norm, color, bgColor) {
            const startAngle = Math.PI;
            const endAngle = startAngle + norm * Math.PI;
            ctx.beginPath();
            ctx.arc(cx, cy, radius, startAngle, startAngle + Math.PI);
            ctx.strokeStyle = bgColor || '#dfe6e9';
            ctx.lineWidth = 6;
            ctx.lineCap = 'round';
            ctx.stroke();

            ctx.beginPath();
            ctx.arc(cx, cy, radius, startAngle, endAngle);
            ctx.strokeStyle = color || '#0077be';
            ctx.lineWidth = 6;
            ctx.lineCap = 'round';
            ctx.shadowColor = color || '#0077be';
            ctx.shadowBlur = 10;
            ctx.stroke();
            ctx.shadowBlur = 0;

            const needleAngle = endAngle;
            const nx = cx + radius * Math.cos(needleAngle);
            const ny = cy + radius * Math.sin(needleAngle);
            ctx.beginPath();
            ctx.arc(nx, ny, 5, 0, 2 * Math.PI);
            ctx.fillStyle = color || '#0077be';
            ctx.shadowColor = color || '#0077be';
            ctx.shadowBlur = 14;
            ctx.fill();
            ctx.shadowBlur = 0;
        }

        function updateGauge(key, norm, color, bgColor) {
            const canvas = cardElements[key].canvas;
            const ctx = canvas.getContext('2d');
            const w = canvas.width, h = canvas.height;
            ctx.clearRect(0, 0, w, h);
            const cx = w / 2;
            const cy = h - 10;
            const radius = Math.min(w, h * 2) / 2.3;
            drawGauge(ctx, cx, cy, radius, norm, color, bgColor);
        }

        let previousAlertState = {};

        async function updateDashboard() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();

                const values = data.values;
                const online = data.online;
                const stale = data.stale;
                const inAlert = data.in_alert;
                const ranges = data.ranges;
                const fmt = data.fmt;
                const units = data.units;
                const labels = data.labels;
                const timestamps = data.timestamps;
                const datetimes = data.datetimes;
                const lastUpdate = data.last_update;
                const globalAnomaly = data.global_anomaly;
                const perSensorAlerts = data.per_sensor_alerts || {};

                if (lastUpdate) {
                    const d = new Date(lastUpdate);
                    document.getElementById('globalUpdate').textContent = 'Updated: ' + d.toLocaleTimeString('en-IN', { hour12: false });
                }
                const badge = document.getElementById('globalAnomalyBadge');
                if (globalAnomaly) {
                    badge.style.display = 'inline-block';
                } else {
                    badge.style.display = 'none';
                }

                let newAlert = false;
                SENSOR_KEYS.forEach(key => {
                    const wasAlert = previousAlertState[key] || false;
                    const nowAlert = inAlert[key] || false;
                    if (nowAlert && !wasAlert) {
                        newAlert = true;
                    }
                    previousAlertState[key] = nowAlert;
                });
                if (newAlert) {
                    playBeep(880, 300, 0.4);
                }

                SENSOR_KEYS.forEach(key => {
                    const el = cardElements[key];
                    const val = values[key];
                    const isOnline = online[key] || false;
                    const isStale = stale[key] || false;
                    const isAlert = inAlert[key] || false;

                    const card = el.card;
                    card.classList.remove('alert', 'stale', 'offline');
                    if (isAlert && isOnline) {
                        card.classList.add('alert');
                    } else if (isStale) {
                        card.classList.add('stale');
                    } else if (!isOnline) {
                        card.classList.add('offline');
                    }

                    const dot = el.dot;
                    dot.className = 'dot';
                    if (isOnline && !isStale) {
                        dot.classList.add('online');
                    } else if (isStale) {
                        dot.classList.add('stale');
                    } else {
                        dot.classList.add('offline');
                    }

                    const low = ranges[key] ? ranges[key][0] : 0;
                    const high = ranges[key] ? ranges[key][1] : 1;
                    el.range.textContent = `Range: ${low.toFixed(1)} – ${high.toFixed(1)} ${units[key]}`;
                    el.unit.textContent = units[key];

                    const valEl = el.value;
                    valEl.className = 'value';
                    if (val !== null && !isNaN(val) && isOnline) {
                        const txt = fmt[key].replace('{', '').replace('}', '').replace(':.', '').replace('f', '');
                        let formatted;
                        if (txt.includes('.')) {
                            const decimals = parseInt(txt.split('.')[1] || '0');
                            formatted = Number(val).toFixed(decimals);
                        } else {
                            formatted = Math.round(val);
                        }
                        valEl.textContent = formatted;
                        if (isAlert) {
                            valEl.classList.add('alert');
                        } else {
                            valEl.classList.remove('alert', 'stale', 'offline');
                        }
                    } else if (isStale && val !== null && !isNaN(val)) {
                        const txt = fmt[key].replace('{', '').replace('}', '').replace(':.', '').replace('f', '');
                        let formatted;
                        if (txt.includes('.')) {
                            const decimals = parseInt(txt.split('.')[1] || '0');
                            formatted = Number(val).toFixed(decimals);
                        } else {
                            formatted = Math.round(val);
                        }
                        valEl.textContent = formatted;
                        valEl.classList.add('stale');
                    } else {
                        valEl.textContent = '---';
                        valEl.classList.add('offline');
                    }

                    const statusEl = el.status;
                    statusEl.className = 'status';
                    if (isOnline && !isStale) {
                        if (isAlert) {
                            statusEl.textContent = '⚠ ALERT';
                            statusEl.classList.add('alert');
                        } else {
                            statusEl.textContent = '● NOMINAL';
                            statusEl.classList.add('ideal');
                        }
                    } else if (isStale) {
                        statusEl.textContent = '⚠ STALE';
                        statusEl.classList.add('stale');
                    } else {
                        statusEl.textContent = '✕ OFFLINE';
                        statusEl.classList.add('offline');
                    }

                    const ts = timestamps[key];
                    const dt = datetimes[key];
                    let displayTs = '—';
                    if (dt && dt !== '') {
                        try {
                            const d = new Date(dt.replace(' ', 'T') + 'Z');
                            displayTs = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
                        } catch(e) {}
                    } else if (ts !== null && !isNaN(ts)) {
                        try {
                            const d = new Date(ts);
                            displayTs = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
                        } catch(e) {}
                    }
                    el.ts.textContent = `Last: ${displayTs}`;

                    let norm = 0;
                    let gaugeColor = '#dfe6e9';
                    let bgColor = '#dfe6e9';
                    if (val !== null && !isNaN(val) && isOnline) {
                        const span = high - low;
                        const extLow = low - span * 0.2;
                        const extHigh = high + span * 0.2;
                        norm = Math.max(0, Math.min(1, (val - extLow) / (extHigh - extLow)));
                        if (isAlert) {
                            gaugeColor = '#ff6b6b';
                            bgColor = '#ff6b6b';
                        } else {
                            gaugeColor = '#0077be';
                            bgColor = '#0077be';
                        }
                    } else {
                        norm = 0;
                        gaugeColor = '#dfe6e9';
                        bgColor = '#dfe6e9';
                    }
                    updateGauge(key, norm, gaugeColor, bgColor);
                });

            } catch (err) {
                console.error('Update error:', err);
            }
        }

        setInterval(updateDashboard, 2000);
        updateDashboard();
    </script>
</body>
</html>
"""

# ---------- Run Flask ----------
if __name__ == '__main__':
    print("✨ Starting Futuristic Sensor Dashboard (with Data Collection)")
    print("Open http://localhost:5000 in your browser.")
    print("Click 'Refresh Dataset' to fetch historical data and retrain the model.")
    app.run(debug=False, host='0.0.0.0', port=5000)