-- ============================================================
-- Alex Financial Planner — Core Database Schema (Migration 001)
-- ------------------------------------------------------------
-- Purpose:
--   Initial schema for a multi-user financial planning platform
--   backed by Aurora PostgreSQL via the RDS Data API.
--
-- Key Concepts:
--   * users          – profile and long-term planning targets
--   * instruments    – reference data for tradable securities
--   * accounts       – user-level investment wrappers (401k, IRA, etc.)
--   * positions      – holdings within accounts
--   * jobs           – async analysis jobs & agent outputs
--
-- Notes:
--   * JSONB is used for flexible allocations and agent payloads
--   * UUIDs are used for primary keys where appropriate
--   * Triggers keep updated_at timestamps in sync automatically
-- ============================================================


-- ============================================================
-- Extensions
-- ============================================================

-- Enable UUID extension (required for uuid_generate_v4())
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ============================================================
-- Users
-- ============================================================

-- Minimal users table (Clerk handles authentication)
CREATE TABLE IF NOT EXISTS users (
    clerk_user_id           VARCHAR(255) PRIMARY KEY,
    display_name            VARCHAR(255),
    years_until_retirement  INTEGER,
    target_retirement_income DECIMAL(12,2),  -- Annual income goal in dollars

    -- Allocation targets for rebalancing (stored as JSONB)
    asset_class_targets     JSONB DEFAULT '{"equity": 70, "fixed_income": 30}',
    region_targets          JSONB DEFAULT '{"north_america": 50, "international": 50}',

    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);


-- ============================================================
-- Instruments
-- ============================================================

-- Reference data for tradable instruments (ETFs, stocks, funds, etc.)
CREATE TABLE IF NOT EXISTS instruments (
    symbol                  VARCHAR(20) PRIMARY KEY,
    name                    VARCHAR(255) NOT NULL,
    instrument_type         VARCHAR(50),       -- e.g. 'equity', 'etf', 'mutual_fund', 'bond_fund'
    current_price           DECIMAL(12,4),     -- Current price for portfolio calculations

    -- Allocation percentages (0–100, stored as JSONB)
    allocation_regions      JSONB DEFAULT '{}',      -- {"north_america": 60, "europe": 20, ...}
    allocation_sectors      JSONB DEFAULT '{}',      -- {"technology": 30, "healthcare": 20, ...}
    allocation_asset_class  JSONB DEFAULT '{}',      -- {"equity": 80, "fixed_income": 20}

    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);


-- ============================================================
-- Accounts
-- ============================================================

-- User-level investment accounts (401k, Roth IRA, taxable, etc.)
CREATE TABLE IF NOT EXISTS accounts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clerk_user_id   VARCHAR(255) REFERENCES users(clerk_user_id) ON DELETE CASCADE,
    account_name    VARCHAR(255) NOT NULL,      -- e.g. "401k", "Roth IRA"
    account_purpose TEXT,                       -- e.g. "Long-term retirement savings"
    cash_balance    DECIMAL(12,2) DEFAULT 0,    -- Uninvested cash
    cash_interest   DECIMAL(5,4)  DEFAULT 0,    -- Annual rate (0.045 = 4.5%)

    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);


-- ============================================================
-- Positions
-- ============================================================

-- Current holdings per account (one row per symbol per account)
CREATE TABLE IF NOT EXISTS positions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id  UUID        REFERENCES accounts(id) ON DELETE CASCADE,
    symbol      VARCHAR(20) REFERENCES instruments(symbol),
    quantity    DECIMAL(20,8) NOT NULL,   -- Supports fractional shares
    as_of_date  DATE DEFAULT CURRENT_DATE,

    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW(),

    -- Ensure a single row per (account, symbol) pair
    UNIQUE(account_id, symbol)
);


-- ============================================================
-- Jobs
-- ============================================================

-- Jobs for async analysis and multi-agent pipelines
CREATE TABLE IF NOT EXISTS jobs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clerk_user_id       VARCHAR(255) REFERENCES users(clerk_user_id) ON DELETE CASCADE,
    job_type            VARCHAR(50) NOT NULL,       -- e.g. 'portfolio_analysis', 'rebalance'
    status              VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'running', 'completed', 'failed'
    request_payload     JSONB,                      -- Input parameters for the job

    -- Separate agent result payloads (no merging or overwriting required)
    report_payload      JSONB,                      -- Reporter agent: narrative / markdown
    charts_payload      JSONB,                      -- Charter agent: visualisation data
    retirement_payload  JSONB,                      -- Retirement agent: projections
    summary_payload     JSONB,                      -- Planner: final summary / metadata

    error_message       TEXT,

    created_at          TIMESTAMP DEFAULT NOW(),
    started_at          TIMESTAMP,
    completed_at        TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT NOW()
);


-- ============================================================
-- Indexes
-- ============================================================

-- Common query patterns:
--   * Fetch all accounts for a user
--   * Fetch all positions for an account or symbol
--   * Filter jobs by user or status

CREATE INDEX IF NOT EXISTS idx_accounts_user
    ON accounts (clerk_user_id);

CREATE INDEX IF NOT EXISTS idx_positions_account
    ON positions (account_id);

CREATE INDEX IF NOT EXISTS idx_positions_symbol
    ON positions (symbol);

CREATE INDEX IF NOT EXISTS idx_jobs_user
    ON jobs (clerk_user_id);

CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs (status);


-- ============================================================
-- Automatic updated_at Triggers
-- ============================================================

-- Shared trigger function to keep updated_at in sync
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach the trigger to all tables that have an updated_at column
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_instruments_updated_at
    BEFORE UPDATE ON instruments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_accounts_updated_at
    BEFORE UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_positions_updated_at
    BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
