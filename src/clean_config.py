"""Named cleaning thresholds derived from M3 profiling."""

# Positive-precipitation-only borough-specific upper IQR fences.
# Keep the full calculated floating-point values to reproduce profiling.
PRECIPITATION_UPPER_FENCE_MM = {
    "BRONX": 3.0999999999999996,
    "BROOKLYN": 2.8499999999999996,
    "MANHATTAN": 2.95,
    "QUEENS": 3.0999999999999996,
    "STATEN ISLAND": 3.0999999999999996,
}

# Borough-specific upper IQR fences for hourly wind speed.
# Values above these thresholds are flagged, never removed or modified.
WIND_SPEED_UPPER_FENCE_KMH = {
    "BRONX": 25.8,
    "BROOKLYN": 24.699999999999996,
    "MANHATTAN": 24.1,
    "QUEENS": 23.849999999999998,
    "STATEN ISLAND": 29.650000000000002,
}

BATCH_SIZE = 5000
