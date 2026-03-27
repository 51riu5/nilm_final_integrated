#include <WiFi.h>
#include <HTTPClient.h>
#include <PZEM004Tv30.h>

// WiFi credentials
const char* ssid = "Johan";
const char* password = "12345678";

// Your backend URL (CHANGE THIS)
const char* serverName = "http://172.20.10.4:8000/api/v1/readings";

// PZEM setup (ESP32 XIAO C3)
PZEM004Tv30 pzem(Serial1, 9, 10); // RX=9, TX=10

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("Connecting to WiFi...");

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nConnected to WiFi");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
}

void loop() {

  // Read sensor values
  float voltage = pzem.voltage();
  float current = pzem.current();
  float power = pzem.power();
  float energy = pzem.energy();
  float frequency = pzem.frequency();
  float pf = pzem.pf();

  // Handle NaN values
  if (isnan(voltage)) voltage = 0;
  if (isnan(current)) current = 0;
  if (isnan(power)) power = 0;
  if (isnan(energy)) energy = 0;
  if (isnan(frequency)) frequency = 0;
  if (isnan(pf)) pf = 0;

  Serial.println("Sending data...");

  if (WiFi.status() == WL_CONNECTED) {

    HTTPClient http;
    http.begin(serverName);
    http.addHeader("Content-Type", "application/json");

    // JSON payload
    String json = "{";
    json += "\"device_id\":\"esp32_1\",";
    json += "\"meter_id\":\"pzem_1\",";
    json += "\"site_id\":\"home_1\",";
    json += "\"voltage_v\":" + String(voltage) + ",";
    json += "\"current_a\":" + String(current) + ",";
    json += "\"power_w\":" + String(power) + ",";
    json += "\"energy_kwh\":" + String(energy) + ",";
    json += "\"frequency_hz\":" + String(frequency) + ",";
    json += "\"power_factor\":" + String(pf);
    json += "}";

    // Send POST request
    int httpResponseCode = http.POST(json);

    Serial.print("HTTP Response: ");
    Serial.println(httpResponseCode);

    // Optional: print response
    String response = http.getString();
    Serial.println(response);

    http.end();

  } else {
    Serial.println("WiFi Disconnected");
  }

  Serial.println("--------------------------");

  delay(1000); // send every 1 sec
}