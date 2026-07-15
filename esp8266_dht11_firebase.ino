// esp8266_dht11_firebase.ino
#include <ESP8266WiFi.h>
#include <Firebase_ESP_Client.h>
#include <DHT.h>
#include <time.h>                     // for NTP

// WiFi Credentials
#define WIFI_SSID "Airtel_sahi_0849"
#define WIFI_PASSWORD "air99772"

// Firebase Credentials
#define API_KEY "AIzaSyDRK3k7DJ1NmGATWMjcKUmzYiVcxYDsOIQ"
#define DATABASE_URL "https://project-67b08-default-rtdb.firebaseio.com"
#define USER_EMAIL "sb284160@gmail.com"
#define USER_PASSWORD "Password@1"

// DHT11
#define DHTPIN D2
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

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

// Convert epoch ms to ISO datetime string (UTC)
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
    dht.begin();
    Serial.println("DHT11 initialized");

    // Connect to WiFi
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        Serial.print(".");
        delay(500);
    }
    Serial.println("\n✅ WiFi connected. IP: " + WiFi.localIP().toString());

    setupNTP();

    // Configure Firebase
    config.api_key = API_KEY;
    config.database_url = DATABASE_URL;
    auth.user.email = USER_EMAIL;
    auth.user.password = USER_PASSWORD;

    Firebase.begin(&config, &auth);
    Firebase.reconnectWiFi(true);

    delay(1000);

    if (Firebase.ready()) {
        Serial.println("✅ Firebase authenticated!");
        // Test write to /test_dht (matches test_* rule)
        if (Firebase.RTDB.setString(&fbdo, "/test_dht", "ok")) {
            Serial.println("✅ Test write succeeded.");
        } else {
            Serial.println("❌ Test write FAILED: " + fbdo.errorReason());
        }
    } else {
        Serial.println("❌ Firebase auth FAILED.");
    }
}

// ---------- Loop ----------
void loop() {
    if (!Firebase.ready()) {
        delay(1000);
        return;
    }

    if (millis() - lastUpdateTime >= UPDATE_INTERVAL) {
        sendLatestData();
        lastUpdateTime = millis();
    }

    if (millis() - lastHistoryTime >= HISTORY_INTERVAL) {
        sendHistoryData();
        lastHistoryTime = millis();
    }
}

// ---------- Send latest data ----------
void sendLatestData() {
    float humidity = dht.readHumidity();
    float temperature = dht.readTemperature();

    if (isnan(humidity) || isnan(temperature)) {
        Serial.println("❌ Failed to read from DHT11 sensor!");
        return;
    }

    unsigned long ts = getTimestamp();
    String datetime = formatDateTime(ts);

    FirebaseJson json;
    json.set("value", temperature);               // primary value (for rule compatibility)
    json.set("unit", "°C");
    json.set("timestamp", ts);
    json.set("datetime", datetime);               // human‑readable
    json.set("temperature", temperature);         // keep for backward compatibility
    json.set("humidity", humidity);
    json.set("unit_temp", "°C");
    json.set("unit_hum", "%");

    String path = "/machines/machine_01/devices/dht11/latest";
    if (Firebase.RTDB.setJSON(&fbdo, path, &json)) {
        Serial.printf("🌡️ T: %.1f°C, 💧 H: %.1f%% | %s → sent\n",
                      temperature, humidity, datetime.c_str());
    } else {
        Serial.println("❌ Failed: " + fbdo.errorReason());
    }
}

// ---------- Send history data ----------
void sendHistoryData() {
    float humidity = dht.readHumidity();
    float temperature = dht.readTemperature();

    if (isnan(humidity) || isnan(temperature)) {
        Serial.println("❌ Failed to read DHT11 for history!");
        return;
    }

    unsigned long ts = getTimestamp();
    String datetime = formatDateTime(ts);

    FirebaseJson json;
    json.set("value", temperature);
    json.set("unit", "°C");
    json.set("timestamp", ts);
    json.set("datetime", datetime);
    json.set("temperature", temperature);
    json.set("humidity", humidity);
    json.set("unit_temp", "°C");
    json.set("unit_hum", "%");

    String path = "/machines/machine_01/devices/dht11/history/" + String(ts);
    if (Firebase.RTDB.setJSON(&fbdo, path, &json)) {
        Serial.println("📝 History saved");
    } else {
        Serial.println("❌ Failed to save history: " + fbdo.errorReason());
    }
}