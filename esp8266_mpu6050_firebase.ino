// esp8266_mpu6050_firebase.ino
#include <ESP8266WiFi.h>
#include <Firebase_ESP_Client.h>
#include <Wire.h>
#include <MPU6050.h>
#include <time.h>

// WiFi
#define WIFI_SSID "Airtel_sahi_0849"
#define WIFI_PASSWORD "air99772"

// Firebase
#define API_KEY "AIzaSyDRK3k7DJ1NmGATWMjcKUmzYiVcxYDsOIQ"
#define DATABASE_URL "https://project-67b08-default-rtdb.firebaseio.com"
#define USER_EMAIL "sb284160@gmail.com"
#define USER_PASSWORD "Password@1"

// MPU6050
MPU6050 mpu;
int16_t ax, ay, az, gx, gy, gz;

FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig config;

unsigned long lastUpdateTime = 0;
unsigned long lastHistoryTime = 0;
const unsigned long UPDATE_INTERVAL = 2000;
const unsigned long HISTORY_INTERVAL = 10000;

bool ntpSynced = false;

// ---------- NTP setup (fixed) ----------
void setupNTP() {
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");
    Serial.print("Waiting for NTP");
    time_t now = time(nullptr);
    int attempts = 0;
    // Wait until we get a time after 2020-01-01 (1577836800) but with a timeout
    while (now < 1577836800UL && attempts < 30) {
        delay(500);
        Serial.print(".");
        now = time(nullptr);
        attempts++;
    }
    if (now >= 1577836800UL) {
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
        // Fallback: use millis() + base epoch (Jan 1, 2025 00:00:00 UTC)
        const unsigned long BASE_EPOCH_MS = 1735689600000UL; // 2025-01-01
        return BASE_EPOCH_MS + millis();
    }
}

String formatDateTime(unsigned long epoch_ms) {
    time_t epoch_sec = epoch_ms / 1000;
    struct tm* timeinfo = gmtime(&epoch_sec);
    if (!timeinfo) return "1970-01-01 00:00:00";
    char buffer[30];
    strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", timeinfo);
    return String(buffer);
}

// ---------- Setup ----------
void setup() {
    Serial.begin(115200);
    Serial.println("\n🔄 MPU6050 Vibration Sensor");

    Wire.begin(D2, D1);
    mpu.initialize();
    if (mpu.testConnection()) Serial.println("✅ MPU6050 connected");
    else Serial.println("❌ MPU6050 connection failed!");

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) { Serial.print("."); delay(500); }
    Serial.println("\n✅ WiFi connected. IP: " + WiFi.localIP().toString());

    setupNTP();

    config.api_key = API_KEY;
    config.database_url = DATABASE_URL;
    auth.user.email = USER_EMAIL;
    auth.user.password = USER_PASSWORD;
    Firebase.begin(&config, &auth);
    Firebase.reconnectWiFi(true);

    delay(1000);
    if (Firebase.ready()) {
        Serial.println("✅ Firebase authenticated!");
        if (Firebase.RTDB.setString(&fbdo, "/test_mpu", "ok")) {
            Serial.println("✅ Test write succeeded.");
        } else {
            Serial.println("❌ Test write FAILED: " + fbdo.errorReason());
        }
    } else {
        Serial.println("❌ Firebase auth FAILED.");
    }
}

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

void sendLatestData() {
    mpu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
    float fax = ax / 16384.0, fay = ay / 16384.0, faz = az / 16384.0;
    float fgx = gx / 131.0, fgy = gy / 131.0, fgz = gz / 131.0;
    float vibration = sqrt(fax*fax + fay*fay + faz*faz);

    unsigned long ts = getTimestamp();
    String datetime = formatDateTime(ts);

    FirebaseJson json;
    json.set("value", vibration);
    json.set("unit", "g");
    json.set("timestamp", ts);
    json.set("datetime", datetime);
    json.set("ax", fax);
    json.set("ay", fay);
    json.set("az", faz);
    json.set("gx", fgx);
    json.set("gy", fgy);
    json.set("gz", fgz);

    String path = "/machines/machine_01/devices/mpu6050/latest";
    if (Firebase.RTDB.setJSON(&fbdo, path, &json)) {
        Serial.printf("📈 vibration=%.3f g | %s → sent\n", vibration, datetime.c_str());
    } else {
        Serial.println("❌ Failed: " + fbdo.errorReason());
    }
}

void sendHistoryData() {
    mpu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
    float fax = ax / 16384.0, fay = ay / 16384.0, faz = az / 16384.0;
    float fgx = gx / 131.0, fgy = gy / 131.0, fgz = gz / 131.0;
    float vibration = sqrt(fax*fax + fay*fay + faz*faz);

    unsigned long ts = getTimestamp();
    String datetime = formatDateTime(ts);

    FirebaseJson json;
    json.set("value", vibration);
    json.set("unit", "g");
    json.set("timestamp", ts);
    json.set("datetime", datetime);
    json.set("ax", fax);
    json.set("ay", fay);
    json.set("az", faz);
    json.set("gx", fgx);
    json.set("gy", fgy);
    json.set("gz", fgz);

    String path = "/machines/machine_01/devices/mpu6050/history/" + String(ts);
    if (Firebase.RTDB.setJSON(&fbdo, path, &json)) {
        Serial.printf("📝 History saved | %s\n", datetime.c_str());
    } else {
        Serial.println("❌ Failed to save history: " + fbdo.errorReason());
    }
}