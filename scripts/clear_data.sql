-- Clear all runtime data from trading_bot database
-- Run this in pgAdmin, DBeaver, or psql connected to the database

-- Disable foreign key checks
SET session_replication_role = 'replica';

-- Clear runtime data tables (keep users, user_settings, symbols)
TRUNCATE TABLE
    signal_confirmations,
    signals,
    candles,
    paper_positions,
    paper_accounts,
    strategy_stats,
    backtests,
    system_logs
RESTART IDENTITY CASCADE;

-- Re-enable foreign key checks
SET session_replication_role = 'origin';

-- Verify
SELECT 'signals' as table_name, count(*) as remaining FROM signals
UNION ALL SELECT 'signal_confirmations', count(*) FROM signal_confirmations
UNION ALL SELECT 'candles', count(*) FROM candles
UNION ALL SELECT 'paper_positions', count(*) FROM paper_positions
UNION ALL SELECT 'paper_accounts', count(*) FROM paper_accounts
UNION ALL SELECT 'strategy_stats', count(*) FROM strategy_stats
UNION ALL SELECT 'backtests', count(*) FROM backtests
UNION ALL SELECT 'system_logs', count(*) FROM system_logs;