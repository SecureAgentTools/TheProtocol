-- PostgreSQL Security Configuration
-- Role-based access control with least privilege principle

-- Create application-specific roles
CREATE ROLE agentvault_readonly NOLOGIN;
CREATE ROLE agentvault_readwrite NOLOGIN;
CREATE ROLE agentvault_admin NOLOGIN;

-- Create schema with restricted access
CREATE SCHEMA IF NOT EXISTS agentvault AUTHORIZATION postgres;

-- Grant permissions to roles
-- Read-only role
GRANT USAGE ON SCHEMA agentvault TO agentvault_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA agentvault TO agentvault_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA agentvault GRANT SELECT ON TABLES TO agentvault_readonly;

-- Read-write role (for application)
GRANT USAGE ON SCHEMA agentvault TO agentvault_readwrite;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA agentvault TO agentvault_readwrite;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA agentvault TO agentvault_readwrite;
ALTER DEFAULT PRIVILEGES IN SCHEMA agentvault GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agentvault_readwrite;
ALTER DEFAULT PRIVILEGES IN SCHEMA agentvault GRANT USAGE, SELECT ON SEQUENCES TO agentvault_readwrite;

-- Admin role (for migrations)
GRANT ALL ON SCHEMA agentvault TO agentvault_admin;
GRANT ALL ON ALL TABLES IN SCHEMA agentvault TO agentvault_admin;
GRANT ALL ON ALL SEQUENCES IN SCHEMA agentvault TO agentvault_admin;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA agentvault TO agentvault_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA agentvault GRANT ALL ON TABLES TO agentvault_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA agentvault GRANT ALL ON SEQUENCES TO agentvault_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA agentvault GRANT ALL ON FUNCTIONS TO agentvault_admin;

-- Create application users (passwords should be set via environment variables)
DO $$
DECLARE
    app_password text;
    admin_password text;
BEGIN
    -- Get passwords from environment or generate secure defaults
    app_password := current_setting('agentvault.app_password', true);
    admin_password := current_setting('agentvault.admin_password', true);
    
    -- Create application user
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'agentvault_app') THEN
        CREATE USER agentvault_app WITH 
            PASSWORD COALESCE(app_password, md5(random()::text))
            NOSUPERUSER 
            NOCREATEDB 
            NOCREATEROLE 
            LOGIN
            CONNECTION LIMIT 100;
        GRANT agentvault_readwrite TO agentvault_app;
    END IF;
    
    -- Create admin user for migrations
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'agentvault_migrator') THEN
        CREATE USER agentvault_migrator WITH 
            PASSWORD COALESCE(admin_password, md5(random()::text))
            NOSUPERUSER 
            NOCREATEDB 
            NOCREATEROLE 
            LOGIN
            CONNECTION LIMIT 10;
        GRANT agentvault_admin TO agentvault_migrator;
    END IF;
END $$;

-- Revoke dangerous PUBLIC permissions
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Enable row-level security for sensitive tables (to be applied after tables are created)
-- Example: ALTER TABLE agentvault.developers ENABLE ROW LEVEL SECURITY;

-- Create audit schema for security logging
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION postgres;

-- Audit log table
CREATE TABLE IF NOT EXISTS audit.security_log (
    id BIGSERIAL PRIMARY KEY,
    event_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    event_type VARCHAR(50) NOT NULL,
    user_name VARCHAR(100),
    client_addr INET,
    details JSONB,
    success BOOLEAN DEFAULT TRUE
);

-- Index for efficient querying
CREATE INDEX idx_security_log_time ON audit.security_log(event_time DESC);
CREATE INDEX idx_security_log_type ON audit.security_log(event_type);
CREATE INDEX idx_security_log_user ON audit.security_log(user_name);

-- Grant minimal permissions on audit schema
GRANT USAGE ON SCHEMA audit TO agentvault_readwrite;
GRANT INSERT ON audit.security_log TO agentvault_readwrite;
GRANT USAGE ON SEQUENCE audit.security_log_id_seq TO agentvault_readwrite;

-- Enable pgcrypto for encryption functions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Function to log security events
CREATE OR REPLACE FUNCTION audit.log_security_event(
    p_event_type VARCHAR(50),
    p_user_name VARCHAR(100),
    p_details JSONB DEFAULT NULL,
    p_success BOOLEAN DEFAULT TRUE
) RETURNS VOID AS $$
BEGIN
    INSERT INTO audit.security_log (event_type, user_name, client_addr, details, success)
    VALUES (p_event_type, p_user_name, inet_client_addr(), p_details, p_success);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute permission on audit function
GRANT EXECUTE ON FUNCTION audit.log_security_event TO agentvault_readwrite;

-- Connection limits and timeouts will be set in postgresql.conf
