
PRAGMA foreign_keys = ON;

-- =========================================================
-- 1. CLEAN SERVICE REQUESTS
-- Grain: one row per NYC 311 request.
-- Primary key: unique_key
-- =========================================================

CREATE TABLE IF NOT EXISTS service_requests_clean (
    unique_key TEXT PRIMARY KEY NOT NULL
        REFERENCES service_requests(unique_key),

    agency_id INTEGER NOT NULL REFERENCES agencies(agency_id),
    borough_id INTEGER NOT NULL REFERENCES boroughs(borough_id),
    complaint_type_id INTEGER NOT NULL
        REFERENCES complaint_types(complaint_type_id),
    status_id INTEGER NOT NULL
        REFERENCES request_statuses(status_id),
    channel_id INTEGER NOT NULL
        REFERENCES submission_channels(channel_id),

    created_date_source TEXT NOT NULL,
    created_local_date TEXT NOT NULL,
    created_local_hour INTEGER NOT NULL
        CHECK (created_local_hour BETWEEN 0 AND 23),

    created_at_utc_raw TEXT,
    created_at_utc TEXT,
    created_at_utc_flag TEXT NOT NULL
        CHECK (created_at_utc_flag IN (
            'ok',
            'ambiguous_local_time',
            'nonexistent_local_time'
        )),

    closed_date_source TEXT,
    closed_at_utc_raw TEXT,
    closed_at_utc TEXT,
    closed_at_utc_flag TEXT NOT NULL
        CHECK (closed_at_utc_flag IN (
            'ok',
            'missing_not_reported',
            'ambiguous_local_time',
            'nonexistent_local_time',
            'invalid_before_created'
        )),

    due_date_source TEXT,
    due_at_utc_raw TEXT,
    due_at_utc TEXT,
    due_at_utc_flag TEXT NOT NULL
        CHECK (due_at_utc_flag IN (
            'ok',
            'missing_not_reported',
            'ambiguous_local_time',
            'nonexistent_local_time',
            'invalid_before_created'
        )),

    resolution_action_updated_date_source TEXT,
    resolution_action_updated_at_utc_raw TEXT,
    resolution_action_updated_at_utc TEXT,
    resolution_action_updated_at_utc_flag TEXT NOT NULL
        CHECK (resolution_action_updated_at_utc_flag IN (
            'ok',
            'missing_not_reported',
            'ambiguous_local_time',
            'nonexistent_local_time',
            'invalid_before_created'
        )),

    latitude_raw REAL,
    latitude REAL,
    latitude_flag TEXT NOT NULL
        CHECK (latitude_flag IN (
            'ok',
            'missing_not_reported',
            'invalid_range'
        )),

    longitude_raw REAL,
    longitude REAL,
    longitude_flag TEXT NOT NULL
        CHECK (longitude_flag IN (
            'ok',
            'missing_not_reported',
            'invalid_range'
        )),

    retrieved_at TEXT NOT NULL,

    CHECK (
        (created_at_utc_flag = 'ok' AND created_at_utc IS NOT NULL)
        OR
        (created_at_utc_flag != 'ok' AND created_at_utc IS NULL)
    ),

    CHECK (
        closed_at_utc_flag != 'invalid_before_created'
        OR closed_at_utc IS NULL
    ),

    CHECK (
        due_at_utc_flag != 'invalid_before_created'
        OR due_at_utc IS NULL
    ),

    CHECK (
        resolution_action_updated_at_utc_flag != 'invalid_before_created'
        OR resolution_action_updated_at_utc IS NULL
    ),

    CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
    CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180)
) STRICT;


-- =========================================================
-- 2. CLEAN WEATHER OBSERVATIONS
-- Grain: one row per location and UTC hour.
-- Primary key: weather_location_id + observed_at_utc
-- =========================================================

CREATE TABLE IF NOT EXISTS weather_observations_clean (
    weather_location_id INTEGER NOT NULL
        REFERENCES weather_locations(weather_location_id),

    observed_at_utc TEXT NOT NULL,

    temperature_2m_c_raw REAL,
    temperature_2m_c REAL,
    temperature_2m_c_flag TEXT NOT NULL
        CHECK (temperature_2m_c_flag IN (
            'ok', 'missing_not_reported', 'unusual_low', 'unusual_high'
        )),

    relative_humidity_2m_pct_raw REAL,
    relative_humidity_2m_pct REAL,
    relative_humidity_2m_pct_flag TEXT NOT NULL
        CHECK (relative_humidity_2m_pct_flag IN (
            'ok', 'missing_not_reported', 'unusual_low', 'unusual_high', 'invalid_range'
        )),

    precipitation_mm_raw REAL,
    precipitation_mm REAL,
    precipitation_mm_flag TEXT NOT NULL
        CHECK (precipitation_mm_flag IN (
            'ok', 'missing_not_reported', 'unusual_high', 'invalid_negative'
        )),

    weather_code_raw INTEGER,
    weather_code INTEGER,
    weather_code_flag TEXT NOT NULL
        CHECK (weather_code_flag IN (
            'ok', 'missing_not_reported', 'invalid_code'
        )),

    wind_speed_10m_kmh_raw REAL,
    wind_speed_10m_kmh REAL,
    wind_speed_10m_kmh_flag TEXT NOT NULL
        CHECK (wind_speed_10m_kmh_flag IN (
            'ok', 'missing_not_reported', 'unusual_high', 'invalid_negative'
        )),

    wind_direction_10m_degrees_raw REAL,
    wind_direction_10m_degrees REAL,
    wind_direction_10m_degrees_flag TEXT NOT NULL
        CHECK (wind_direction_10m_degrees_flag IN (
            'ok', 'missing_not_reported', 'invalid_range'
        )),

    cloud_cover_pct_raw REAL,
    cloud_cover_pct REAL,
    cloud_cover_pct_flag TEXT NOT NULL
        CHECK (cloud_cover_pct_flag IN (
            'ok', 'missing_not_reported', 'invalid_range'
        )),

    retrieved_at TEXT NOT NULL,

    PRIMARY KEY (weather_location_id, observed_at_utc),

    FOREIGN KEY (weather_location_id, observed_at_utc)
        REFERENCES weather_observations(
            weather_location_id, observed_at_utc
        ),

    CHECK (
        precipitation_mm_flag != 'invalid_negative'
        OR precipitation_mm IS NULL
    ),

    CHECK (
        wind_speed_10m_kmh_flag != 'invalid_negative'
        OR wind_speed_10m_kmh IS NULL
    ),

    CHECK (
        weather_code_flag != 'invalid_code'
        OR weather_code IS NULL
    ),

    CHECK (
        wind_direction_10m_degrees_flag != 'invalid_range'
        OR wind_direction_10m_degrees IS NULL
    ),

    CHECK (
        cloud_cover_pct_flag != 'invalid_range'
        OR cloud_cover_pct IS NULL
    )
) STRICT;


-- =========================================================
-- 3. CATEGORY ALIAS MAPPING
-- Stores human-approved category/name decisions.
-- =========================================================

CREATE TABLE IF NOT EXISTS category_alias_map (
    entity_type TEXT NOT NULL
        CHECK (entity_type IN (
            'agency_code',
            'agency_name',
            'borough_name',
            'complaint_type',
            'status_name',
            'channel_name',
            'location_code'
        )),

    source_label TEXT NOT NULL,
    canonical_label TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    note TEXT NOT NULL,

    PRIMARY KEY (entity_type, source_label)
) STRICT;


-- =========================================================
-- 4. IDENTITY MAPPING
-- Stores human-approved identity resolution decisions.
-- =========================================================

CREATE TABLE IF NOT EXISTS identity_alias_map (
    entity_type TEXT NOT NULL
        CHECK (entity_type IN (
            'service_request',
            'agency',
            'borough',
            'complaint_type',
            'request_status',
            'submission_channel',
            'weather_location'
        )),

    source_id TEXT NOT NULL,
    canonical_source_id TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    note TEXT NOT NULL,

    PRIMARY KEY (entity_type, source_id)
) STRICT;
