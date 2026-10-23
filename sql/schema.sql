-- M2 database schema for NYC 311 and Open-Meteo.
-- All tables are STRICT.
-- Normalized timestamps ending in _utc use ISO 8601 UTC text.
-- Original source timestamps are retained separately because the source
-- uses floating timestamps without an explicit timezone.
-- DST-ambiguous/nonexistent times are retained with a quality status;
-- no arbitrary UTC timestamp is assigned.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agencies (
    agency_id INTEGER PRIMARY KEY,
    agency_code TEXT NOT NULL UNIQUE
        CHECK (length(trim(agency_code)) > 0),
    agency_name TEXT NOT NULL
        CHECK (length(trim(agency_name)) > 0),
    retrieved_at TEXT NOT NULL
        CHECK (
            length(retrieved_at) IN (20, 24, 27)
            AND substr(retrieved_at, 11, 1) = 'T'
            AND substr(retrieved_at, -1, 1) = 'Z'
        )
) STRICT;

CREATE TABLE IF NOT EXISTS boroughs (
    borough_id INTEGER PRIMARY KEY,
    borough_name TEXT NOT NULL UNIQUE
        CHECK (length(trim(borough_name)) > 0),
    retrieved_at TEXT NOT NULL
        CHECK (
            length(retrieved_at) IN (20, 24, 27)
            AND substr(retrieved_at, 11, 1) = 'T'
            AND substr(retrieved_at, -1, 1) = 'Z'
        )
) STRICT;

CREATE TABLE IF NOT EXISTS complaint_types (
    complaint_type_id INTEGER PRIMARY KEY,
    complaint_type TEXT NOT NULL UNIQUE
        CHECK (length(trim(complaint_type)) > 0),
    retrieved_at TEXT NOT NULL
        CHECK (
            length(retrieved_at) IN (20, 24, 27)
            AND substr(retrieved_at, 11, 1) = 'T'
            AND substr(retrieved_at, -1, 1) = 'Z'
        )
) STRICT;

CREATE TABLE IF NOT EXISTS request_statuses (
    status_id INTEGER PRIMARY KEY,
    status_name TEXT NOT NULL UNIQUE
        CHECK (length(trim(status_name)) > 0),
    retrieved_at TEXT NOT NULL
        CHECK (
            length(retrieved_at) IN (20, 24, 27)
            AND substr(retrieved_at, 11, 1) = 'T'
            AND substr(retrieved_at, -1, 1) = 'Z'
        )
) STRICT;

CREATE TABLE IF NOT EXISTS submission_channels (
    channel_id INTEGER PRIMARY KEY,
    channel_name TEXT NOT NULL UNIQUE
        CHECK (length(trim(channel_name)) > 0),
    retrieved_at TEXT NOT NULL
        CHECK (
            length(retrieved_at) IN (20, 24, 27)
            AND substr(retrieved_at, 11, 1) = 'T'
            AND substr(retrieved_at, -1, 1) = 'Z'
        )
) STRICT;

CREATE TABLE IF NOT EXISTS weather_locations (
    weather_location_id INTEGER PRIMARY KEY,
    location_code TEXT NOT NULL UNIQUE
        CHECK (length(trim(location_code)) > 0),
    borough_id INTEGER NOT NULL UNIQUE,
    requested_latitude REAL NOT NULL
        CHECK (requested_latitude BETWEEN -90 AND 90),
    requested_longitude REAL NOT NULL
        CHECK (requested_longitude BETWEEN -180 AND 180),
    grid_latitude REAL NOT NULL
        CHECK (grid_latitude BETWEEN -90 AND 90),
    grid_longitude REAL NOT NULL
        CHECK (grid_longitude BETWEEN -180 AND 180),
    timezone TEXT NOT NULL
        CHECK (timezone = 'America/New_York'),
    retrieved_at TEXT NOT NULL
        CHECK (
            length(retrieved_at) IN (20, 24, 27)
            AND substr(retrieved_at, 11, 1) = 'T'
            AND substr(retrieved_at, -1, 1) = 'Z'
        ),
    FOREIGN KEY (borough_id) REFERENCES boroughs(borough_id)
) STRICT;

CREATE TABLE IF NOT EXISTS service_requests (
    -- Source identifier is the natural primary key for a request.
    unique_key TEXT PRIMARY KEY NOT NULL
        CHECK (length(trim(unique_key)) > 0),

    -- Exact source strings are preserved independently of UTC conversion.
    created_date_source TEXT NOT NULL
        CHECK (length(trim(created_date_source)) > 0),
    created_at_utc TEXT
        CHECK (
            created_at_utc IS NULL
            OR (
                length(created_at_utc) IN (20, 24, 27)
                AND substr(created_at_utc, 11, 1) = 'T'
                AND substr(created_at_utc, -1, 1) = 'Z'
            )
        ),
    created_local_date TEXT NOT NULL
        CHECK (
            created_local_date GLOB
            '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
        ),
    created_local_hour INTEGER NOT NULL
        CHECK (created_local_hour BETWEEN 0 AND 23),
    created_timestamp_status TEXT NOT NULL
        CHECK (
            created_timestamp_status IN (
                'normalized',
                'ambiguous_local_time',
                'nonexistent_local_time'
            )
        ),


    agency_id INTEGER NOT NULL,
    borough_id INTEGER NOT NULL,
    complaint_type_id INTEGER NOT NULL,
    status_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,

    -- Optional source timestamps. Unresolvable local timestamps remain
    -- available as source text, with no fabricated UTC value.
    closed_date_source TEXT,
    closed_at_utc TEXT
        CHECK (
            closed_at_utc IS NULL
            OR (
                length(closed_at_utc) IN (20, 24, 27)
                AND substr(closed_at_utc, 11, 1) = 'T'
                AND substr(closed_at_utc, -1, 1) = 'Z'
            )
        ),
    closed_timestamp_status TEXT NOT NULL
        CHECK (
            closed_timestamp_status IN (
                'missing',
                'normalized',
                'ambiguous_local_time',
                'nonexistent_local_time'
            )
        ),


    due_date_source TEXT,
    due_at_utc TEXT
        CHECK (
            due_at_utc IS NULL
            OR (
                length(due_at_utc) IN (20, 24, 27)
                AND substr(due_at_utc, 11, 1) = 'T'
                AND substr(due_at_utc, -1, 1) = 'Z'
            )
        ),
    due_timestamp_status TEXT NOT NULL
        CHECK (
            due_timestamp_status IN (
                'missing',
                'normalized',
                'ambiguous_local_time',
                'nonexistent_local_time'
            )
        ),


    resolution_action_updated_date_source TEXT,
    resolution_action_updated_at_utc TEXT
        CHECK (
            resolution_action_updated_at_utc IS NULL
            OR (
                length(resolution_action_updated_at_utc) IN (20, 24, 27)
                AND substr(resolution_action_updated_at_utc, 11, 1) = 'T'
                AND substr(resolution_action_updated_at_utc, -1, 1) = 'Z'
            )
        ),
    resolution_updated_timestamp_status TEXT NOT NULL
        CHECK (
            resolution_updated_timestamp_status IN (
                'missing',
                'normalized',
                'ambiguous_local_time',
                'nonexistent_local_time'
            )
        ),


    descriptor TEXT,
    descriptor_2 TEXT,
    location_type TEXT,
    incident_zip TEXT,
    incident_address TEXT,
    street_name TEXT,
    cross_street_1 TEXT,
    cross_street_2 TEXT,
    intersection_street_1 TEXT,
    intersection_street_2 TEXT,
    address_type TEXT,
    city TEXT,
    landmark TEXT,
    community_board TEXT,
    council_district TEXT,
    police_precinct TEXT,
    bbl TEXT,
    x_coordinate_state_plane REAL,
    y_coordinate_state_plane REAL,
    park_facility_name TEXT,
    park_borough TEXT,
    latitude REAL
        CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
    longitude REAL
        CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180),
    location_json TEXT,
    facility_type TEXT,
    resolution_description TEXT,
    road_ramp TEXT,
    bridge_highway_direction TEXT,
    bridge_highway_name TEXT,
    bridge_highway_segment TEXT,
    taxi_company_borough TEXT,
    taxi_pick_up_location TEXT,
    vehicle_type TEXT,

    retrieved_at TEXT NOT NULL
        CHECK (
            length(retrieved_at) IN (20, 24, 27)
            AND substr(retrieved_at, 11, 1) = 'T'
            AND substr(retrieved_at, -1, 1) = 'Z'
        ),

    CHECK (
        (
            created_timestamp_status = 'normalized'
            AND created_at_utc IS NOT NULL
        )
        OR
        (
            created_timestamp_status IN (
                'ambiguous_local_time',
                'nonexistent_local_time'
            )
            AND created_at_utc IS NULL
        )
    ),

    CHECK (
        (
            closed_timestamp_status = 'missing'
            AND closed_date_source IS NULL
            AND closed_at_utc IS NULL
        )
        OR
        (
            closed_timestamp_status = 'normalized'
            AND closed_date_source IS NOT NULL
            AND closed_at_utc IS NOT NULL
        )
        OR
        (
            closed_timestamp_status IN (
                'ambiguous_local_time',
                'nonexistent_local_time'
            )
            AND closed_date_source IS NOT NULL
            AND closed_at_utc IS NULL
        )
    ),

    CHECK (
        (
            due_timestamp_status = 'missing'
            AND due_date_source IS NULL
            AND due_at_utc IS NULL
        )
        OR
        (
            due_timestamp_status = 'normalized'
            AND due_date_source IS NOT NULL
            AND due_at_utc IS NOT NULL
        )
        OR
        (
            due_timestamp_status IN (
                'ambiguous_local_time',
                'nonexistent_local_time'
            )
            AND due_date_source IS NOT NULL
            AND due_at_utc IS NULL
        )
    ),

    CHECK (
        (
            resolution_updated_timestamp_status = 'missing'
            AND resolution_action_updated_date_source IS NULL
            AND resolution_action_updated_at_utc IS NULL
        )
        OR
        (
            resolution_updated_timestamp_status = 'normalized'
            AND resolution_action_updated_date_source IS NOT NULL
            AND resolution_action_updated_at_utc IS NOT NULL
        )
        OR
        (
            resolution_updated_timestamp_status IN (
                'ambiguous_local_time',
                'nonexistent_local_time'
            )
            AND resolution_action_updated_date_source IS NOT NULL
            AND resolution_action_updated_at_utc IS NULL
        )
    ),

    FOREIGN KEY (agency_id) REFERENCES agencies(agency_id),
    FOREIGN KEY (borough_id) REFERENCES boroughs(borough_id),
    FOREIGN KEY (complaint_type_id)
        REFERENCES complaint_types(complaint_type_id),
    FOREIGN KEY (status_id) REFERENCES request_statuses(status_id),
    FOREIGN KEY (channel_id) REFERENCES submission_channels(channel_id)
) STRICT;

CREATE TABLE IF NOT EXISTS weather_observations (
    -- Grain: one observation per weather location and UTC hour.
    weather_location_id INTEGER NOT NULL,
    observed_at_utc TEXT NOT NULL
        CHECK (
            length(observed_at_utc) = 20
            AND substr(observed_at_utc, 11, 1) = 'T'
            AND substr(observed_at_utc, 15, 5) = '00:00'
            AND substr(observed_at_utc, -1, 1) = 'Z'
        ),

    temperature_2m_c REAL,
    relative_humidity_2m_pct REAL
        CHECK (
            relative_humidity_2m_pct IS NULL
            OR relative_humidity_2m_pct BETWEEN 0 AND 100
        ),
    precipitation_mm REAL
        CHECK (precipitation_mm IS NULL OR precipitation_mm >= 0),
    weather_code INTEGER,
    wind_speed_10m_kmh REAL
        CHECK (wind_speed_10m_kmh IS NULL OR wind_speed_10m_kmh >= 0),
    wind_direction_10m_degrees REAL
        CHECK (
            wind_direction_10m_degrees IS NULL
            OR wind_direction_10m_degrees BETWEEN 0 AND 360
        ),
    cloud_cover_pct REAL
        CHECK (
            cloud_cover_pct IS NULL
            OR cloud_cover_pct BETWEEN 0 AND 100
        ),

    retrieved_at TEXT NOT NULL
        CHECK (
            length(retrieved_at) IN (20, 24, 27)
            AND substr(retrieved_at, 11, 1) = 'T'
            AND substr(retrieved_at, -1, 1) = 'Z'
        ),

    PRIMARY KEY (weather_location_id, observed_at_utc),
    FOREIGN KEY (weather_location_id)
        REFERENCES weather_locations(weather_location_id)
) STRICT;

CREATE TABLE IF NOT EXISTS quarantine_records (
    quarantine_id INTEGER PRIMARY KEY,
    source_kind TEXT NOT NULL
        CHECK (source_kind IN ('nyc311', 'weather')),
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL
        CHECK (source_row_number > 0),
    source_record_key TEXT,
    reason_code TEXT NOT NULL
        CHECK (length(trim(reason_code)) > 0),
    reason_detail TEXT NOT NULL
        CHECK (length(trim(reason_detail)) > 0),
    raw_record_json TEXT NOT NULL,
    retrieved_at TEXT NOT NULL
        CHECK (
            length(retrieved_at) IN (20, 24, 27)
            AND substr(retrieved_at, 11, 1) = 'T'
            AND substr(retrieved_at, -1, 1) = 'Z'
        ),
    UNIQUE (source_kind, source_file, source_row_number, reason_code)
) STRICT;

-- Keep indexes focused on likely analytical access patterns.
CREATE INDEX IF NOT EXISTS idx_requests_borough_date_hour
    ON service_requests (borough_id, created_local_date, created_local_hour);

CREATE INDEX IF NOT EXISTS idx_requests_complaint_date
    ON service_requests (complaint_type_id, created_local_date);

CREATE INDEX IF NOT EXISTS idx_requests_created_utc
    ON service_requests (created_at_utc);


CREATE INDEX IF NOT EXISTS idx_requests_local_date
    ON service_requests (created_local_date);
