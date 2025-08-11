# Turbo Ping Bot Configuration

## Telegram Bot Configuration
```
BOT_TOKEN=6123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
BOT_USERNAME=turbo_ping_bot
```

## Payment Configuration

### TON (The Open Network) - Primary Payment Method
```
TON_WALLET_ADDRESS=EQBvW8Z5huBkMJYdnfAEM5JqTNkuWX3diqYENkWsIL0XggGG
TON_PRIVATE_KEY=ed25519_private_key_here_for_verification
TON_NETWORK=mainnet
TON_API_ENDPOINT=https://toncenter.com/api/v2/
TON_API_KEY=your_ton_api_key_here
```

### Telegram Stars - Secondary Payment Method
```
TELEGRAM_STARS_PROVIDER_TOKEN=284685063:TEST:your_provider_token_here
TELEGRAM_STARS_ENABLED=true
```

### Backup Crypto Payment Providers
```
# NOWPayments (Backup)
NOWPAYMENTS_API_KEY=your_nowpayments_api_key_here
NOWPAYMENTS_IPN_SECRET=your_ipn_secret_here

# Coinbase Commerce (Backup)
COINBASE_API_KEY=your_coinbase_api_key_here
COINBASE_WEBHOOK_SECRET=your_webhook_secret_here
```

## Database Configuration
```
# PostgreSQL (Production)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=turbo_ping_db
DB_USER=turbo_ping_user
DB_PASSWORD=secure_password_123
DB_URL=postgresql://turbo_ping_user:secure_password_123@localhost:5432/turbo_ping_db

# SQLite (Development/Testing)
SQLITE_DB_PATH=./turbo_ping.db
```

## Admin Panel Configuration
```
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj6hsxq5S/kG
ADMIN_SECRET_KEY=your-secret-key-for-sessions-here-make-it-long-and-random
ADMIN_SESSION_EXPIRE_HOURS=24
```

## VPN/Proxy Servers Configuration
```
# Server Regions
REGIONS=US,EU,ASIA,RU

# US Servers
US_PROXY_HOST=us1.turbo-ping.com
US_PROXY_PORT=8080
US_PROXY_USERNAME=us_user_
US_PROXY_PASSWORD=us_pass_

# EU Servers  
EU_PROXY_HOST=eu1.turbo-ping.com
EU_PROXY_PORT=8080
EU_PROXY_USERNAME=eu_user_
EU_PROXY_PASSWORD=eu_pass_

# Asia Servers
ASIA_PROXY_HOST=asia1.turbo-ping.com
ASIA_PROXY_PORT=8080
ASIA_PROXY_USERNAME=asia_user_
ASIA_PROXY_PASSWORD=asia_pass_

# Russia Servers
RU_PROXY_HOST=ru1.turbo-ping.com
RU_PROXY_PORT=8080
RU_PROXY_USERNAME=ru_user_
RU_PROXY_PASSWORD=ru_pass_
```

## Subscription Plans
```
# Plan Pricing (in USD)
MONTHLY_PLAN_PRICE=9.99
QUARTERLY_PLAN_PRICE=24.99
YEARLY_PLAN_PRICE=89.99

# Trial Configuration
TRIAL_DAYS=7
TRIAL_ENABLED=true

# Referral Configuration
REFERRAL_COMMISSION_PERCENT=20
MINIMUM_PAYOUT_USD=50
```

## Observer Service Configuration
```
OBSERVER_CHECK_INTERVAL_MINUTES=10
REMINDER_DAYS_BEFORE_EXPIRY=7,1
ADMIN_ALERT_CHAT_ID=123456789
```

## Security Configuration
```
# Encryption Key for Credentials (Fernet)
ENCRYPTION_KEY=your-fernet-encryption-key-here-32-bytes-base64-encoded

# Rate Limiting
RATE_LIMIT_REQUESTS_PER_MINUTE=30
RATE_LIMIT_BURST=10
```

## Logging Configuration
```
LOG_LEVEL=INFO
LOG_FILE=./logs/turbo_ping.log
LOG_MAX_SIZE_MB=100
LOG_BACKUP_COUNT=5
```

## Development/Testing Flags
```
DEBUG_MODE=true
TESTING_MODE=false
MOCK_PAYMENTS=false
SKIP_PAYMENT_VERIFICATION=false
```

---

## Notes:
- This configuration is for development purposes with hardcoded values
- In production, use environment variables and secure key management
- TON payments have priority over Telegram Stars and other crypto methods
- All sensitive credentials should be encrypted at rest
- Admin password hash is for 'admin123' - change in production
