#include <PZEM004Tv30.h>

// For ESP32 XIAO C3, use hardware serial or software serial
PZEM004Tv30 pzem(Serial1, 9, 10); // RX=GPIO9, TX=GPIO10

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("==============================");
  Serial.println("PZEM-004T Energy Monitor");
  Serial.println("by Johan Sergi");a
  Serial.println("ESP32 XIAO C3 Version");
  Serial.println("==============================");
  Serial.println();
  delay(500);
}

void loop() {
  Serial.println("--- Reading Sensor Data ---");
  
  float voltage = pzem.voltage();
  if (!isnan(voltage)) {
    Serial.print("Voltage: ");
    Serial.print(voltage);
    Serial.println(" V");
  } else {
    Serial.println("Error reading voltage");
  }
  
  float current = pzem.current();
  if (!isnan(current)) {
    Serial.print("Current: ");
    Serial.print(current);
    Serial.println(" A");
  } else {
    Serial.println("Error reading current");
  }
  
  float power = pzem.power();
  if (!isnan(power)) {
    Serial.print("Power: ");
    Serial.print(power);
    Serial.println(" W");
  } else {
    Serial.println("Error reading power");
  }
  
  float energy = pzem.energy();
  if (!isnan(energy)) {
    Serial.print("Energy: ");
    Serial.print(energy, 3);
    Serial.println(" kWh");
  } else {
    Serial.println("Error reading energy");
  }
  
  float frequency = pzem.frequency();
  if (!isnan(frequency)) {
    Serial.print("Frequency: ");
    Serial.print(frequency, 1);
    Serial.println(" Hz");
  } else {
    Serial.println("Error reading frequency");
  }
  
  float pf = pzem.pf();
  if (!isnan(pf)) {
    Serial.print("Power Factor: ");
    Serial.println(pf);
  } else {
    Serial.println("Error reading power factor");
  }
  
  Serial.println("==============================");
  Serial.println();
  delay(2000);
}