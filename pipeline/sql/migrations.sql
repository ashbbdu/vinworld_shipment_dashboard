-- Pipeline v2 migration tables
-- Run once against the target database (lvs_prod_db / lvs_uat_db)

CREATE TABLE IF NOT EXISTS job_runs (
    id VARCHAR(36) PRIMARY KEY,
    job_type VARCHAR(50) NOT NULL,
    status ENUM('running', 'completed', 'failed') DEFAULT 'running',
    total_shipments INT DEFAULT 0,
    processed_count INT DEFAULT 0,
    failed_count INT DEFAULT 0,
    error_summary TEXT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,
    INDEX idx_type_status (job_type, status)
);

CREATE TABLE IF NOT EXISTS shipment_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shipment_id VARCHAR(100) NOT NULL,
    job_type ENUM('excel_ingest', 'air_sync', 'sea_sync', 'sea_reverse', 'nightly_retry', 'recovery') NOT NULL,
    job_run_id VARCHAR(36) NOT NULL,
    status ENUM('pending', 'in_progress', 'completed', 'failed') DEFAULT 'pending',
    retry_count INT DEFAULT 0,
    lifetime_retry_count INT DEFAULT 0,
    error_message TEXT NULL,
    started_at DATETIME NULL,
    completed_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_shipment (shipment_id),
    INDEX idx_job_run (job_run_id),
    FOREIGN KEY (job_run_id) REFERENCES job_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS excel_imports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    sftp_path VARCHAR(500) NULL,
    file_size_bytes BIGINT NULL,
    file_modified_at DATETIME NULL,
    row_count INT DEFAULT 0,
    new_shipment_count INT DEFAULT 0,
    job_run_id VARCHAR(36) NOT NULL,
    status ENUM('downloaded', 'parsed', 'processing', 'completed', 'failed') DEFAULT 'downloaded',
    local_path VARCHAR(500) NULL,
    s3_archive_path VARCHAR(500) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_job_run (job_run_id),
    FOREIGN KEY (job_run_id) REFERENCES job_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS excel_import_rows (
    id INT AUTO_INCREMENT PRIMARY KEY,
    excel_import_id INT NOT NULL,
    shipment_id VARCHAR(100) NOT NULL,
    raw_row_data JSON NULL,
    is_new BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (excel_import_id) REFERENCES excel_imports(id) ON DELETE CASCADE,
    INDEX idx_shipment (shipment_id),
    INDEX idx_import (excel_import_id)
);
