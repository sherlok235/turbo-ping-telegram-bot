-- Turbo Ping Telegram Bot Database Schema
-- PostgreSQL/MySQL compatible schema

-- Enable UUID extension for PostgreSQL
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    language_code VARCHAR(10) DEFAULT 'en',
    referral_code VARCHAR(50) UNIQUE NOT NULL,
    referred_by_user_id INTEGER REFERENCES users(id),
    region VARCHAR(10) DEFAULT 'US',
    is_active BOOLEAN DEFAULT true,
    is_admin BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Subscription plans table
CREATE TABLE subscription_plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    duration_days INTEGER NOT NULL,
    price_usd DECIMAL(10,2) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User subscriptions table
CREATE TABLE subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id INTEGER NOT NULL REFERENCES subscription_plans(id),
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'active', -- active, expired, cancelled, trial
    is_trial BOOLEAN DEFAULT false,
    trial_days_remaining INTEGER DEFAULT 0,
    auto_renew BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Payments table
CREATE TABLE payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_id INTEGER REFERENCES subscriptions(id),
    payment_method VARCHAR(50) NOT NULL, -- 'ton', 'telegram_stars', 'nowpayments', 'coinbase'
    amount_usd DECIMAL(10,2) NOT NULL,
    amount_crypto DECIMAL(20,8),
    crypto_currency VARCHAR(10),
    transaction_hash VARCHAR(255),
    telegram_payment_charge_id VARCHAR(255),
    ton_transaction_id VARCHAR(255),
    payment_provider_id VARCHAR(255),
    status VARCHAR(20) DEFAULT 'pending', -- pending, completed, failed, cancelled
    payment_data JSONB, -- Store additional payment provider data
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    UNIQUE(transaction_hash),
    UNIQUE(telegram_payment_charge_id),
    UNIQUE(ton_transaction_id)
);

-- Referrals table
CREATE TABLE referrals (
    id SERIAL PRIMARY KEY,
    referrer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    referred_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    commission_amount_usd DECIMAL(10,2) DEFAULT 0.00,
    commission_paid BOOLEAN DEFAULT false,
    payment_id INTEGER REFERENCES payments(id), -- Payment that generated the commission
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    paid_at TIMESTAMP,
    UNIQUE(referrer_id, referred_user_id)
);

-- Referral payouts table
CREATE TABLE referral_payouts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount_usd DECIMAL(10,2) NOT NULL,
    payout_method VARCHAR(50), -- 'ton', 'usdt', 'manual'
    payout_address VARCHAR(255),
    status VARCHAR(20) DEFAULT 'requested', -- requested, processing, completed, failed
    admin_notes TEXT,
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- VPN/Proxy credentials table (encrypted)
CREATE TABLE proxy_credentials (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    region VARCHAR(10) NOT NULL,
    proxy_host VARCHAR(255) NOT NULL,
    proxy_port INTEGER NOT NULL,
    proxy_username_encrypted TEXT NOT NULL, -- Fernet encrypted
    proxy_password_encrypted TEXT NOT NULL, -- Fernet encrypted
    is_active BOOLEAN DEFAULT true,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP,
    UNIQUE(user_id, region)
);

-- Bot messages/instructions table
CREATE TABLE bot_messages (
    id SERIAL PRIMARY KEY,
    message_key VARCHAR(100) UNIQUE NOT NULL,
    message_text TEXT NOT NULL,
    language_code VARCHAR(10) DEFAULT 'en',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Admin audit log
CREATE TABLE admin_audit_log (
    id SERIAL PRIMARY KEY,
    admin_user_id INTEGER REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    target_user_id INTEGER REFERENCES users(id),
    details JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Observer service logs
CREATE TABLE observer_logs (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(50) NOT NULL, -- 'expiry_check', 'reminder', 'revocation'
    user_id INTEGER REFERENCES users(id),
    subscription_id INTEGER REFERENCES subscriptions(id),
    status VARCHAR(20) NOT NULL, -- 'success', 'failed', 'skipped'
    message TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for better performance
CREATE INDEX idx_users_telegram_id ON users(telegram_id);
CREATE INDEX idx_users_referral_code ON users(referral_code);
CREATE INDEX idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX idx_subscriptions_status ON subscriptions(status);
CREATE INDEX idx_subscriptions_end_date ON subscriptions(end_date);
CREATE INDEX idx_payments_user_id ON payments(user_id);
CREATE INDEX idx_payments_status ON payments(status);
CREATE INDEX idx_payments_transaction_hash ON payments(transaction_hash);
CREATE INDEX idx_referrals_referrer_id ON referrals(referrer_id);
CREATE INDEX idx_referrals_referred_user_id ON referrals(referred_user_id);
CREATE INDEX idx_proxy_credentials_user_id ON proxy_credentials(user_id);
CREATE INDEX idx_admin_audit_log_admin_user_id ON admin_audit_log(admin_user_id);
CREATE INDEX idx_observer_logs_created_at ON observer_logs(created_at);

-- Insert default subscription plans
INSERT INTO subscription_plans (name, duration_days, price_usd, description) VALUES
('Monthly Plan', 30, 9.99, 'Monthly VPN/Proxy access with region switching'),
('Quarterly Plan', 90, 24.99, 'Quarterly VPN/Proxy access with region switching (Save 17%)'),
('Yearly Plan', 365, 89.99, 'Yearly VPN/Proxy access with region switching (Save 25%)');

-- Insert default bot messages
INSERT INTO bot_messages (message_key, message_text, language_code) VALUES
('welcome_message', '🚀 Добро пожаловать в Turbo Ping!\n\nВыберите действие:', 'ru'),
('payment_instructions', '💳 Инструкции по оплате:\n\n1. Выберите план подписки\n2. Оплатите через TON или Telegram Stars\n3. Получите доступы к прокси', 'ru'),
('proxy_instructions', '📋 Инструкции по использованию прокси:\n\n1. Настройте прокси в вашем приложении\n2. Используйте предоставленные IP, логин и пароль\n3. При проблемах обращайтесь в поддержку', 'ru'),
('referral_info', '👥 Реферальная программа:\n\n• Получайте 20% с каждого платежа приглашенного пользователя\n• Минимальная сумма для вывода: $50\n• Выплаты производятся в TON или USDT', 'ru'),
('support_info', '🆘 Поддержка:\n\nДля получения помощи обращайтесь к администратору: @turbo_ping_support', 'ru');

-- Create trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_subscriptions_updated_at BEFORE UPDATE ON subscriptions FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_bot_messages_updated_at BEFORE UPDATE ON bot_messages FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
