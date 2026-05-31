CREATE DATABASE IF NOT EXISTS stockapp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE stockapp;

CREATE TABLE IF NOT EXISTS tickers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(200),
    asset_type ENUM('stock', 'index', 'crypto', 'forex') NOT NULL,
    exchange VARCHAR(50),
    active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_symbol (symbol),
    INDEX idx_asset_type (asset_type),
    INDEX idx_active (active)
);

CREATE TABLE IF NOT EXISTS ohlcv (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticker_id INT NOT NULL,
    date DATE NOT NULL,
    open DECIMAL(20, 6),
    high DECIMAL(20, 6),
    low DECIMAL(20, 6),
    close DECIMAL(20, 6),
    volume BIGINT,
    source VARCHAR(30),
    UNIQUE KEY uq_ticker_date (ticker_id, date),
    INDEX idx_ticker_date (ticker_id, date),
    FOREIGN KEY (ticker_id) REFERENCES tickers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS indicators (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticker_id INT NOT NULL,
    date DATE NOT NULL,
    indicator_name VARCHAR(50) NOT NULL,
    value DECIMAL(30, 8),
    UNIQUE KEY uq_ticker_date_indicator (ticker_id, date, indicator_name),
    INDEX idx_ticker_date_ind (ticker_id, date),
    FOREIGN KEY (ticker_id) REFERENCES tickers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS strategies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    rules_json JSON NOT NULL,
    active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ticker_id INT NOT NULL,
    strategy_id INT NOT NULL,
    date DATE NOT NULL,
    signal_type ENUM('BUY', 'SELL', 'ALERT') NOT NULL,
    details_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_signals_ticker_date (ticker_id, date),
    INDEX idx_signals_strategy (strategy_id),
    FOREIGN KEY (ticker_id) REFERENCES tickers(id) ON DELETE CASCADE,
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alerts_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    signal_id BIGINT NOT NULL,
    channel VARCHAR(30) NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status ENUM('sent', 'failed', 'skipped') DEFAULT 'sent',
    error_msg TEXT,
    FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
);
