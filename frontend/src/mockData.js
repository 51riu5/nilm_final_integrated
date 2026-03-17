const SITES = ["site-101", "site-202"];
const DEVICES = [
  { device_id: "esp32-a1", meter_id: "main-meter-a1", site_id: "site-101" },
  { device_id: "esp32-a2", meter_id: "main-meter-a2", site_id: "site-202" },
];

const APPLIANCES = [
  { appliance_id: "fridge", appliance_label: "Refrigerator", base: 120 },
  { appliance_id: "hvac", appliance_label: "HVAC", base: 900 },
  { appliance_id: "washer", appliance_label: "Washer", base: 450 },
  { appliance_id: "kettle", appliance_label: "Kettle", base: 1500 },
  { appliance_id: "lighting", appliance_label: "Lighting", base: 180 },
  { appliance_id: "tv", appliance_label: "Television", base: 100 },
];

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function randomFloat(min, max) {
  return min + Math.random() * (max - min);
}

function pickActivePower(base) {
  const isOn = Math.random() > 0.22;
  if (!isOn) {
    return 0;
  }
  return base * randomFloat(0.65, 1.35);
}

function createDisaggregationRecord(device, at, energyAccumulator) {
  const records = APPLIANCES.map((appliance) => {
    const power_w = Number(pickActivePower(appliance.base).toFixed(2));
    const key = `${device.device_id}:${appliance.appliance_id}`;
    const nextEnergy = (energyAccumulator.get(key) || 0) + power_w / 3600000;
    energyAccumulator.set(key, nextEnergy);

    return {
      received_at: at.toISOString(),
      device_id: device.device_id,
      site_id: device.site_id,
      timestamp: at.toISOString(),
      appliance_id: appliance.appliance_id,
      appliance_label: appliance.appliance_label,
      power_w,
      energy_kwh: Number(nextEnergy.toFixed(5)),
      raw: {
        confidence: Number(randomFloat(0.8, 0.99).toFixed(2)),
        model_version: "nilm-v2.4",
      },
    };
  });

  return records;
}

function createMeterRecord(device, at, applianceRecords, meterEnergyAccumulator) {
  const totalPower = applianceRecords.reduce((acc, row) => acc + row.power_w, 0);
  const voltage = Number(randomFloat(224, 239).toFixed(2));
  const current = totalPower > 0 ? Number((totalPower / voltage).toFixed(3)) : 0;
  const key = device.device_id;
  const nextEnergy = (meterEnergyAccumulator.get(key) || 0) + totalPower / 3600000;
  meterEnergyAccumulator.set(key, nextEnergy);

  return {
    received_at: at.toISOString(),
    device_id: device.device_id,
    meter_id: device.meter_id,
    site_id: device.site_id,
    timestamp: at.toISOString(),
    voltage_v: voltage,
    current_a: current,
    power_w: Number(totalPower.toFixed(2)),
    energy_kwh: Number(nextEnergy.toFixed(5)),
    frequency_hz: Number(randomFloat(49.85, 50.15).toFixed(2)),
    power_factor: Number(clamp(randomFloat(0.75, 0.99), 0, 1).toFixed(2)),
    raw: {
      firmware: "sm-v1.9",
      sample_window_s: 1,
    },
  };
}

export function generateMockDataset(points = 90) {
  const now = new Date();
  const meterEnergyAccumulator = new Map();
  const applianceEnergyAccumulator = new Map();

  const meterReadings = [];
  const disaggregatedReadings = [];

  for (let i = points; i >= 1; i -= 1) {
    const at = new Date(now.getTime() - i * 10000);
    DEVICES.forEach((device) => {
      const applianceRows = createDisaggregationRecord(
        device,
        at,
        applianceEnergyAccumulator,
      );
      const meterRow = createMeterRecord(device, at, applianceRows, meterEnergyAccumulator);

      disaggregatedReadings.push(...applianceRows);
      meterReadings.push(meterRow);
    });
  }

  return {
    sites: SITES,
    devices: DEVICES,
    appliances: APPLIANCES,
    meterReadings,
    disaggregatedReadings,
  };
}

export function appendLiveTick(state) {
  const now = new Date();
  const nextMeter = [...state.meterReadings];
  const nextDisaggregation = [...state.disaggregatedReadings];

  const meterEnergyAccumulator = new Map();
  const applianceEnergyAccumulator = new Map();

  state.meterReadings.forEach((row) => {
    meterEnergyAccumulator.set(row.device_id, row.energy_kwh);
  });

  state.disaggregatedReadings.forEach((row) => {
    const key = `${row.device_id}:${row.appliance_id}`;
    applianceEnergyAccumulator.set(key, row.energy_kwh);
  });

  DEVICES.forEach((device) => {
    const applianceRows = createDisaggregationRecord(
      device,
      now,
      applianceEnergyAccumulator,
    );
    const meterRow = createMeterRecord(device, now, applianceRows, meterEnergyAccumulator);

    nextDisaggregation.push(...applianceRows);
    nextMeter.push(meterRow);
  });

  return {
    ...state,
    meterReadings: nextMeter.slice(-500),
    disaggregatedReadings: nextDisaggregation.slice(-2500),
  };
}
