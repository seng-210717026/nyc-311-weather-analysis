-- Analytical query: hourly NYC 311 request volume alongside weather.
--
-- Parameters:
--   :start_date  inclusive local date, YYYY-MM-DD
--   :end_date    exclusive local date, YYYY-MM-DD
--
-- Result grain:
--   one row per borough, local date, local hour, and complaint type.
--
-- created_at_utc is used to find the matching UTC weather hour.
-- Requests with ambiguous/nonexistent local timestamps have no UTC
-- timestamp and are therefore excluded from this time-based join.
-- Boroughs without a weather location (UNSPECIFIED) are excluded.
-- LEFT JOIN preserves counts if an expected weather observation is absent.

WITH request_hours AS (
    SELECT
        b.borough_name,
        sr.created_local_date,
        sr.created_local_hour,
        ct.complaint_type,
        substr(sr.created_at_utc, 1, 13) || ':00:00Z'
            AS observed_at_utc
    FROM service_requests AS sr
    JOIN boroughs AS b
        ON b.borough_id = sr.borough_id
    JOIN complaint_types AS ct
        ON ct.complaint_type_id = sr.complaint_type_id
    WHERE sr.created_at_utc IS NOT NULL
      AND sr.created_local_date >= :start_date
      AND sr.created_local_date < :end_date
),
hourly_counts AS (
    SELECT
        borough_name,
        created_local_date,
        created_local_hour,
        complaint_type,
        observed_at_utc,
        COUNT(*) AS request_count
    FROM request_hours
    GROUP BY
        borough_name,
        created_local_date,
        created_local_hour,
        complaint_type,
        observed_at_utc
)
SELECT
    hc.borough_name,
    hc.created_local_date,
    printf('%02d:00', hc.created_local_hour) AS local_hour,
    hc.complaint_type,
    hc.request_count,
    wo.temperature_2m_c,
    wo.relative_humidity_2m_pct,
    wo.precipitation_mm,
    wo.weather_code,
    wo.wind_speed_10m_kmh,
    CASE
        WHEN wo.observed_at_utc IS NULL THEN 0
        ELSE 1
    END AS weather_matched
FROM hourly_counts AS hc
JOIN boroughs AS b
    ON b.borough_name = hc.borough_name
JOIN weather_locations AS wl
    ON wl.borough_id = b.borough_id
LEFT JOIN weather_observations AS wo
    ON wo.weather_location_id = wl.weather_location_id
   AND wo.observed_at_utc = hc.observed_at_utc
ORDER BY
    hc.request_count DESC,
    hc.borough_name,
    hc.created_local_date,
    hc.created_local_hour,
    hc.complaint_type;
