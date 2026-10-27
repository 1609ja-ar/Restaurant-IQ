-- RestaurantIQ MySQL schema (generated from backend/app/db.py; the app creates these tables automatically).
-- Database: CREATE DATABASE restaurantiq CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE app_state (
	k VARCHAR(64) NOT NULL, 
	v JSON, 
	PRIMARY KEY (k)
)COMMENT='active_dataset, version_counter, settings' ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE uploads (
	upload_id VARCHAR(32) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	file_ext VARCHAR(10) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	stored_path VARCHAR(500) NOT NULL COMMENT 'raw file on disk, relative to RIQ_DATA_DIR', 
	row_count INTEGER, 
	column_count INTEGER, 
	uploaded_at DATETIME NOT NULL, 
	PRIMARY KEY (upload_id)
)COMMENT='Raw uploads (file kept unchanged on disk)' ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE datasets (
	dataset_id VARCHAR(16) NOT NULL, 
	version INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	is_demo BOOL NOT NULL, 
	source_filename VARCHAR(255), 
	source_upload_id VARCHAR(32), 
	file_type VARCHAR(10), 
	raw_rows INTEGER NOT NULL, 
	rows_used INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	meta JSON NOT NULL COMMENT 'mapping, import settings, reconciliation, capabilities, ...', 
	PRIMARY KEY (dataset_id), 
	UNIQUE (version), 
	FOREIGN KEY(source_upload_id) REFERENCES uploads (upload_id)
)COMMENT='Immutable dataset versions (v1, v2, ...)' ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE cleaning_log (
	dataset_id VARCHAR(16) NOT NULL, 
	step_no SMALLINT NOT NULL, 
	step VARCHAR(120) NOT NULL, 
	detail TEXT NOT NULL, 
	rows_affected INTEGER, 
	PRIMARY KEY (dataset_id, step_no), 
	FOREIGN KEY(dataset_id) REFERENCES datasets (dataset_id) ON DELETE CASCADE
)COMMENT='Transformation log per dataset version' ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE column_quality (
	dataset_id VARCHAR(16) NOT NULL, 
	column_name VARCHAR(255) NOT NULL, 
	canonical_field VARCHAR(64), 
	completeness_pct FLOAT(53), 
	uniqueness_pct FLOAT(53), 
	validity_pct FLOAT(53), 
	non_null INTEGER, 
	valid_count INTEGER, 
	note TEXT, 
	PRIMARY KEY (dataset_id, column_name), 
	FOREIGN KEY(dataset_id) REFERENCES datasets (dataset_id) ON DELETE CASCADE
)COMMENT='Data-quality report per column' ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE restaurants (
	dataset_id VARCHAR(16) NOT NULL, 
	rid INTEGER NOT NULL COMMENT 'source row number (1-based)', 
	source_row INTEGER NOT NULL, 
	restaurant_name TEXT, 
	address MEDIUMTEXT, 
	location VARCHAR(700), 
	locality TEXT, 
	city TEXT, 
	region TEXT, 
	country TEXT, 
	rating FLOAT(53) COMMENT 'normalized to 0-5; NULL = unrated / invalid', 
	rating_source FLOAT(53), 
	rating_raw TEXT, 
	review_count FLOAT(53), 
	review_count_raw TEXT, 
	cost FLOAT(53), 
	cost_raw TEXT, 
	currency VARCHAR(16), 
	price_tier VARCHAR(16), 
	online_order BOOL, 
	table_booking BOOL, 
	latitude FLOAT(53), 
	longitude FLOAT(53), 
	review_text MEDIUMTEXT, 
	menu_items MEDIUMTEXT, 
	opening_hours MEDIUMTEXT, 
	source_date DATETIME, 
	is_unrated BOOL NOT NULL, 
	rating_invalid BOOL NOT NULL, 
	votes_invalid BOOL NOT NULL, 
	cost_invalid BOOL NOT NULL, 
	is_invalid BOOL NOT NULL, 
	invalid_reason VARCHAR(255), 
	cost_outlier BOOL NOT NULL, 
	include_in_analysis BOOL NOT NULL, 
	extra_columns JSON COMMENT 'unmapped source columns, preserved as-is', 
	PRIMARY KEY (dataset_id, rid), 
	FOREIGN KEY(dataset_id) REFERENCES datasets (dataset_id) ON DELETE CASCADE
)COMMENT='Cleaned listings (one row per de-duplicated listing)' ENGINE=InnoDB CHARSET=utf8mb4;

CREATE INDEX ix_restaurants_analysis ON restaurants (dataset_id, include_in_analysis);

CREATE INDEX ix_restaurants_location ON restaurants (dataset_id, location);

CREATE TABLE restaurant_cuisines (
	dataset_id VARCHAR(16) NOT NULL, 
	rid INTEGER NOT NULL, 
	pos SMALLINT NOT NULL COMMENT 'order within the source list', 
	cuisine VARCHAR(255) NOT NULL, 
	PRIMARY KEY (dataset_id, rid, pos), 
	FOREIGN KEY(dataset_id, rid) REFERENCES restaurants (dataset_id, rid) ON DELETE CASCADE
)COMMENT='Bridge: restaurant x cuisine' ENGINE=InnoDB CHARSET=utf8mb4;

CREATE INDEX ix_cuisines_name ON restaurant_cuisines (dataset_id, cuisine);

CREATE TABLE restaurant_types (
	dataset_id VARCHAR(16) NOT NULL, 
	rid INTEGER NOT NULL, 
	pos SMALLINT NOT NULL, 
	restaurant_type VARCHAR(255) NOT NULL, 
	PRIMARY KEY (dataset_id, rid, pos), 
	FOREIGN KEY(dataset_id, rid) REFERENCES restaurants (dataset_id, rid) ON DELETE CASCADE
)COMMENT='Bridge: restaurant x restaurant type' ENGINE=InnoDB CHARSET=utf8mb4;

CREATE INDEX ix_types_name ON restaurant_types (dataset_id, restaurant_type);
