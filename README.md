👍 Here's a summary of each endpoint:

1. *GET /health*
    - Checks the API's health status
    - Returns `{"status": "ok"}` if everything's good

2. *POST /api/v1/readings*
    - Ingests a single meter reading
    - Expects a `MeterReading` object
    - Stores the reading in the `meter_readings` table
    - Returns `{"status": "stored", "received_at": <timestamp>}`

3. *POST /api/v1/readings/batch*
    - Ingests a batch of meter readings
    - Expects a `MeterReadingBatch` object with a list of `MeterReading`s
    - Stores each reading in the `meter_readings` table
    - Returns `{"status": "stored", "count": <number_of_readings>}`

4. *POST /api/v1/disaggregation*
    - Ingests a single disaggregated reading
    - Expects a `DisaggregatedReading` object
    - Stores the reading in the `disaggregated_readings` table
    - Returns `{"status": "stored", "received_at": <timestamp>}`

5. *POST /api/v1/disaggregation/batch*
    - Ingests a batch of disaggregated readings
    - Expects a `DisaggregatedReadingBatch` object with a list of `DisaggregatedReading`s
    - Stores each reading in the `disaggregated_readings` table
    - Returns `{"status": "stored", "count": <number_of_readings>}`

6. *GET /api/v1/disaggregation/recent*
    - Retrieves recent disaggregated readings
    - Takes an optional `limit` query parameter (default=50, max=500)
    - Returns a list of recent disaggregated readings in JSON format

7. *GET /api/v1/readings/recent*
    - Retrieves recent meter readings
    - Takes an optional `limit` query parameter (default=50, max=500)
    - Returns a list of recent meter readings in JSON format

Let me know if you'd like more details! 😊

## Frontend Dashboard (Mock NILM Data)

A presentation-focused frontend has been added at `frontend/`.

### What it includes

- React + Vite project with a modern, responsive analytics dashboard UI
- Backend schema-compatible mock data modeled after:
    - `POST /api/v1/readings`
    - `POST /api/v1/disaggregation`
- Live simulation mode that appends new readings every few seconds
- Interactive controls for site, device, and time window
- Visualization elements:
    - Demand and quality trend chart (power, frequency, power factor)
    - Energy and voltage profile chart
    - Appliance consumption bar chart
    - Appliance load share pie chart
    - Recent readings table and operational insight alerts

### Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open the local URL shown by Vite (typically `http://localhost:5173`).

### Build check

```bash
npm run build
```

Build currently succeeds.