// esp8266_zmpt101b_firebase.ino
#include <ESP8266WiFi.h>
#include <Firebase_ESP_Client.h>
#include <ZMPT101B.h>
#include <time.h>                     // for NTP

// WiFi Credentials
#define WIFI_SSID "Airtel_sahi_0849"
#define WIFI_PASSWORD "air99772"

// Firebase Credentials
#define API_KEY "AIzaSyDRK3k7DJ1NmGATWMjcKUmzYiVcxYDsOIQ"
#define DATABASE_URL "https://project-67b08-default-rtdb.firebaseio.com"
#define USER_EMAIL "sb284160@gmail.com"
#define USER_PASSWORD "Password@1"

// ZMPT101B pin
#define VOLTAGE_PIN A0

// ------- ZMPT101B setup ----------
ZMPT101B voltageSensor(VOLTAGE_PIN, 50.0);   // 50 Hz mains frequency

// Calibration
float SENSITIVITY = 218.0;          // Adjust after calibration
const float NOISE_THRESHOLD = 2.0;  // voltage below this -> 0

// Firebase objects
FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig config;

unsigned long lastUpdateTime = 0;
unsigned long lastHistoryTime = 0;
const unsigned long UPDATE_INTERVAL = 2000;
const unsigned long HISTORY_INTERVAL = 10000;

bool ntpSynced = false;

// ---------- NTP setup ----------
void setupNTP() {
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");
    Serial.print("Waiting for NTP");
    time_t now = time(nullptr);
    int attempts = 0;
    while (now < 8 * 3600 * 2 && attempts < 20) {
        delay(500);
        Serial.print(".");
        now = time(nullptr);
        attempts++;
    }
    if (now > 8 * 3600 * 2) {
        ntpSynced = true;
        Serial.println(" done.");
    } else {
        Serial.println(" failed.");
        ntpSynced = false;
    }
}

// ---------- Timestamp helpers ----------
unsigned long getTimestamp() {
    time_t now = time(nullptr);
    if (ntpSynced && now > 1577836800UL) {   // after 2020
        return (unsigned long)now * 1000UL;
    } else {
        // Fallback: use millis() + base epoch (Jan 1, 2026 00:00:00 UTC)
        const unsigned long BASE_EPOCH_MS = 1740000000000UL;
        return BASE_EPOCH_MS + millis();
    }
}

String formatDateTime(unsigned long epoch_ms) {
    time_t epoch_sec = epoch_ms / 1000;
    struct tm* timeinfo = gmtime(&epoch_sec);
    char buffer[30];
    strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", timeinfo);
    return String(buffer);
}

// ---------- Setup ----------
void setup() {
    Serial.begin(115200);
    Serial.println("\n⚡ ZMPT101B AC Voltage Sensor");
    Serial.println("⚠️ WARNING: Working with AC mains is dangerous!");
    Serial.println("Ensure proper isolation and safety measures!");
    delay(2000);

    // WiFi
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        Serial.print(".");
        delay(500);
    }
    Serial.println("\n✅ WiFi connected. IP: " + WiFi.localIP().toString());

    setupNTP();

    // Firebase
    config.api_key = API_KEY;
    config.database_url = DATABASE_URL;
    auth.user.email = USER_EMAIL;
    auth.user.password = USER_PASSWORD;
    Firebase.begin(&config, &auth);
    Firebase.reconnectWiFi(true);

    delay(1000);
    if (Firebase.ready()) {
        Serial.println("✅ Firebase authenticated!");
        // Test write to /test_voltage
        if (Firebase.RTDB.setString(&fbdo, "/test_voltage", "ok")) {
            Serial.println("✅ Test write succeeded.");
        } else {
            Serial.println("❌ Test write FAILED: " + fbdo.errorReason());
        }
    } else {
        Serial.println("❌ Firebase auth FAILED.");
    }

    // Calibration instructions
    Serial.println("\n📐 CALIBRATION:");
    Serial.println("1. Connect to known AC voltage (e.g., mains).");
    Serial.println("2. Measure actual RMS with multimeter.");
    Serial.println("3. Adjust SENSITIVITY until readings match.");
    Serial.println("   Increase if too low, decrease if too high.\n");

    voltageSensor.setSensitivity(SENSITIVITY);
}

// ---------- Read voltage ----------
float readACVoltage() {
    float voltage = voltageSensor.getRmsVoltage();
    if (voltage < NOISE_THRESHOLD) voltage = 0;
    return voltage;
}

// ---------- Loop ----------
void loop() {
    if (!Firebase.ready()) { delay(1000); return; }
    if (millis() - lastUpdateTime >= UPDATE_INTERVAL) {
        sendLatestData();
        lastUpdateTime = millis();
    }
    if (millis() - lastHistoryTime >= HISTORY_INTERVAL) {
        sendHistoryData();
        lastHistoryTime = millis();
    }
}

// ---------- Send latest ----------
void sendLatestData() {
    float voltage = readACVoltage();
    float raw = voltageSensor.getRmsVoltage();
    unsigned long ts = getTimestamp();
    String datetime = formatDateTime(ts);

    FirebaseJson json;
    json.set("value", voltage);
    json.set("unit", "V");
    json.set("timestamp", ts);
    json.set("datetime", datetime);

    String path = "/machines/machine_01/devices/voltage/latest";
    if (Firebase.RTDB.setJSON(&fbdo, path, &json)) {
        Serial.printf("⚡ %.2f V | %s → sent\n", voltage, datetime.c_str());
        Serial.printf("   (raw = %.2f V, sensitivity = %.2f)\n", raw, SENSITIVITY);
    } else {
        Serial.println("❌ Failed: " + fbdo.errorReason());
    }
}

// ---------- Send history ----------
void sendHistoryData() {
    float voltage = readACVoltage();
    unsigned long ts = getTimestamp();
    String datetime = formatDateTime(ts);

    FirebaseJson json;
    json.set("value", voltage);
    json.set("unit", "V");
    json.set("timestamp", ts);
    json.set("datetime", datetime);

    String path = "/machines/machine_01/devices/voltage/history/" + String(ts);
    if (Firebase.RTDB.setJSON(&fbdo, path, &json)) {
        Serial.println("📝 History saved");
    } else {
        Serial.println("❌ Failed to save history: " + fbdo.errorReason());
    }
}