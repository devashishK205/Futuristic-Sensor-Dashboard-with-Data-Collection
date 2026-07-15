import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report
import joblib
import warnings
warnings.filterwarnings('ignore')

# Try importing XGBoost (optional)
try:
    from xgboost import XGBClassifier
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    print("⚠️ XGBoost not installed. Install with: pip install xgboost")

# ---------- Normal ranges ----------
NORMAL_RANGES = {
    'temperature': (20, 40),
    'humidity': (30, 80),
    'voltage': (210, 250),
    'current': (0, 15),
    'vibration': (0, 2.0)
}

# ---------- Configuration ----------
MIN_SAMPLES = 10
TEST_SIZE = 0.2
RANDOM_STATE = 42
CV_FOLDS = 5

def load_data(csv_file='dataset.csv'):
    """Load dataset, ensure all columns exist, and return clean data."""
    try:
        df = pd.read_csv(csv_file)
    except FileNotFoundError:
        print("❌ dataset.csv not found. Run data_collection.py first.")
        return pd.DataFrame()
    required = ['temperature', 'humidity', 'voltage', 'current', 'vibration']
    for col in required:
        if col not in df.columns:
            df[col] = 0
            print(f"⚠️ Column '{col}' missing – added with zeros.")
    df = df[required]
    df = df[(df != 0).any(axis=1)]
    df = df.fillna(method='ffill').fillna(0)
    print(f"Loaded {len(df)} records.")
    return df

def label_data(df):
    """Label rows using the normal ranges."""
    labels = []
    for _, row in df.iterrows():
        fault = False
        for param, (low, high) in NORMAL_RANGES.items():
            val = row.get(param, 0)
            if val < low or val > high:
                fault = True
                break
        labels.append(1 if fault else 0)
    df['label'] = labels
    return df

def generate_synthetic_data(X, y, target_normal=50, target_fault=50, noise_std=0.02):
    """
    Generate synthetic samples to balance the dataset.
    If only one class exists, generate the missing class.
    """
    unique, counts = np.unique(y, return_counts=True)
    class_counts = dict(zip(unique, counts))

    X_aug = X.copy()
    y_aug = y.copy()

    if 0 not in class_counts or class_counts[0] == 0:
        print("⚠️ No Normal samples. Generating synthetic Normal samples...")
        fault_X = X[y == 1]
        if len(fault_X) == 0:
            print("No data. Generating random synthetic data.")
            for _ in range(target_normal + target_fault):
                row = np.array([
                    np.random.uniform(20, 40),
                    np.random.uniform(30, 80),
                    np.random.uniform(210, 250),
                    np.random.uniform(0, 15),
                    np.random.uniform(0, 2.0)
                ])
                X_aug = np.vstack([X_aug, row])
                y_aug = np.append(y_aug, 0 if np.random.rand() > 0.5 else 1)
            return X_aug, y_aug
        n_to_gen = target_normal
        indices = np.random.choice(len(fault_X), n_to_gen, replace=True)
        normal_samples = fault_X[indices].copy()
        for i, (low, high) in enumerate(NORMAL_RANGES.values()):
            col = normal_samples[:, i]
            min_val, max_val = col.min(), col.max()
            if max_val - min_val > 0:
                col = (col - min_val) / (max_val - min_val)
                col = col * (high - low) + low
            else:
                col = np.full_like(col, (low + high) / 2)
            normal_samples[:, i] = col
        normal_samples += np.random.normal(0, noise_std, normal_samples.shape)
        X_aug = np.vstack([X_aug, normal_samples])
        y_aug = np.append(y_aug, np.zeros(n_to_gen))

    if 1 not in class_counts or class_counts[1] == 0:
        print("⚠️ No Fault samples. Generating synthetic Fault samples...")
        normal_X = X[y == 0]
        if len(normal_X) == 0:
            for _ in range(target_fault):
                row = np.array([
                    np.random.uniform(0, 50),
                    np.random.uniform(0, 100),
                    np.random.uniform(0, 300),
                    np.random.uniform(0, 25),
                    np.random.uniform(0, 5)
                ])
                X_aug = np.vstack([X_aug, row])
                y_aug = np.append(y_aug, 1)
            return X_aug, y_aug
        n_to_gen = target_fault
        indices = np.random.choice(len(normal_X), n_to_gen, replace=True)
        fault_samples = normal_X[indices].copy()
        for i, (low, high) in enumerate(NORMAL_RANGES.values()):
            col = fault_samples[:, i]
            mask_high = np.random.rand(len(col)) > 0.5
            col[mask_high] = col[mask_high] * (1 + np.random.uniform(0.1, 0.3))
            col[~mask_high] = col[~mask_high] * (1 - np.random.uniform(0.1, 0.3))
            fault_samples[:, i] = col
        fault_samples += np.random.normal(0, noise_std, fault_samples.shape)
        X_aug = np.vstack([X_aug, fault_samples])
        y_aug = np.append(y_aug, np.ones(n_to_gen))

    print(f"After augmentation: {dict(zip(*np.unique(y_aug, return_counts=True)))}")
    return X_aug, y_aug

def train_and_select_model(df):
    """Train multiple classifiers and select the best."""
    feature_cols = ['temperature', 'humidity', 'voltage', 'current', 'vibration']
    X = df[feature_cols].values
    y = df['label'].values

    if len(X) < MIN_SAMPLES:
        print(f"⚠️ Only {len(X)} samples. Need at least {MIN_SAMPLES}.")
        return None, None

    print(f"Label distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

    # Generate synthetic samples if needed
    X_aug, y_aug = generate_synthetic_data(X, y)

    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X_aug, y_aug, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y_aug
    )

    # Scale
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Define classifiers with basic hyperparameters (will be tuned via GridSearchCV)
    classifiers = {
        'Random Forest': RandomForestClassifier(random_state=RANDOM_STATE),
        'Gradient Boosting': GradientBoostingClassifier(random_state=RANDOM_STATE),
        'SVM': SVC(probability=True, random_state=RANDOM_STATE)
    }
    if XGB_AVAILABLE:
        classifiers['XGBoost'] = XGBClassifier(random_state=RANDOM_STATE, eval_metric='logloss')

    # Simple parameter grids for each
    param_grids = {
        'Random Forest': {
            'n_estimators': [50, 100],
            'max_depth': [10, 20, None],
            'min_samples_split': [2, 5]
        },
        'Gradient Boosting': {
            'n_estimators': [50, 100],
            'learning_rate': [0.05, 0.1],
            'max_depth': [3, 5]
        },
        'SVM': {
            'C': [0.1, 1, 10],
            'gamma': ['scale', 'auto'],
            'kernel': ['rbf', 'linear']
        }
    }
    if XGB_AVAILABLE:
        param_grids['XGBoost'] = {
            'n_estimators': [50, 100],
            'learning_rate': [0.05, 0.1],
            'max_depth': [3, 5]
        }

    best_model = None
    best_score = -1
    best_name = ""
    results = {}

    for name, clf in classifiers.items():
        print(f"\n🔍 Training {name}...")
        grid = GridSearchCV(clf, param_grids[name], cv=min(CV_FOLDS, len(np.unique(y_train))),
                            scoring='accuracy', n_jobs=-1)
        grid.fit(X_train_scaled, y_train)
        best_estimator = grid.best_estimator_
        cv_score = grid.best_score_
        results[name] = cv_score

        # Evaluate on test set
        y_pred = best_estimator.predict(X_test_scaled)
        test_acc = accuracy_score(y_test, y_pred)
        print(f"   Best params: {grid.best_params_}")
        print(f"   Cross-val accuracy: {cv_score:.4f}")
        print(f"   Test accuracy: {test_acc:.4f}")

        if cv_score > best_score:
            best_score = cv_score
            best_model = best_estimator
            best_name = name

    print("\n===== Model Comparison =====")
    for name, score in results.items():
        print(f"  {name}: {score:.4f}")
    print(f"\n✅ Best model: {best_name} with cross-val accuracy {best_score:.4f}")

    # Train the best model on the full training data (optional)
    # Already done via GridSearchCV on the best estimator, but we can re-fit if needed.
    best_model.fit(X_train_scaled, y_train)

    # Save
    joblib.dump(best_model, 'fault_model.pkl')
    joblib.dump(scaler, 'scaler.pkl')
    print("\n✅ Model and scaler saved.")

    return best_model, scaler

def main():
    print("Loading dataset...")
    df = load_data('dataset.csv')
    if df.empty:
        return
    print("Labeling data...")
    df = label_data(df)
    print(f"Label distribution:\n{df['label'].value_counts()}")
    print("\nTraining models and selecting best...")
    train_and_select_model(df)

if __name__ == '__main__':
    main()