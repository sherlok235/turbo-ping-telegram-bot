"""
Configuration parser for reading settings from markdown config file.
Handles parsing of the config/config.md file with hardcoded development values.
"""

import re
import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TelegramConfig:
    bot_token: str
    bot_username: str


@dataclass
class TONConfig:
    wallet_address: str
    private_key: str
    network: str
    api_endpoint: str
    api_key: str


@dataclass
class TelegramStarsConfig:
    provider_token: str
    enabled: bool


@dataclass
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str
    url: str
    sqlite_path: Optional[str] = None


@dataclass
class AdminConfig:
    username: str
    password_hash: str
    secret_key: str
    session_expire_hours: int


@dataclass
class ProxyServerConfig:
    host: str
    port: int
    username_prefix: str
    password_prefix: str


@dataclass
class SubscriptionConfig:
    monthly_price: float
    quarterly_price: float
    yearly_price: float
    trial_days: int
    trial_enabled: bool
    referral_commission_percent: int
    minimum_payout_usd: float


@dataclass
class ObserverConfig:
    check_interval_minutes: int
    reminder_days: List[int]
    admin_alert_chat_id: int


@dataclass
class SecurityConfig:
    encryption_key: str
    rate_limit_requests_per_minute: int
    rate_limit_burst: int


@dataclass
class BotConfig:
    telegram: TelegramConfig
    ton: TONConfig
    telegram_stars: TelegramStarsConfig
    database: DatabaseConfig
    admin: AdminConfig
    proxy_servers: Dict[str, ProxyServerConfig]
    subscription: SubscriptionConfig
    observer: ObserverConfig
    security: SecurityConfig
    debug_mode: bool = False
    log_level: str = "INFO"


class ConfigParser:
    """Parser for markdown configuration file."""
    
    def __init__(self, config_path: str = "config/config.md"):
        self.config_path = Path(config_path)
        self._config_data: Dict[str, str] = {}
        self._load_config()
    
    def _load_config(self) -> None:
        """Load and parse the markdown configuration file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract configuration blocks using regex
        code_blocks = re.findall(r'```\n(.*?)\n```', content, re.DOTALL)
        
        for block in code_blocks:
            lines = block.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    self._config_data[key.strip()] = value.strip()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key."""
        value = self._config_data.get(key, default)
        
        # Type conversion
        if isinstance(value, str):
            # Boolean conversion
            if value.lower() in ('true', 'false'):
                return value.lower() == 'true'
            
            # Integer conversion
            if value.isdigit():
                return int(value)
            
            # Float conversion
            try:
                if '.' in value:
                    return float(value)
            except ValueError:
                pass
        
        return value
    
    def get_list(self, key: str, separator: str = ',', default: List = None) -> List:
        """Get configuration value as list."""
        value = self.get(key, default)
        if isinstance(value, str):
            return [item.strip() for item in value.split(separator)]
        return value or []
    
    def parse_config(self) -> BotConfig:
        """Parse all configuration sections into structured config object."""
        try:
            # Telegram configuration
            telegram_config = TelegramConfig(
                bot_token=self.get('BOT_TOKEN'),
                bot_username=self.get('BOT_USERNAME')
            )
            
            # TON configuration
            ton_config = TONConfig(
                wallet_address=self.get('TON_WALLET_ADDRESS'),
                private_key=self.get('TON_PRIVATE_KEY'),
                network=self.get('TON_NETWORK', 'mainnet'),
                api_endpoint=self.get('TON_API_ENDPOINT'),
                api_key=self.get('TON_API_KEY')
            )
            
            # Telegram Stars configuration
            telegram_stars_config = TelegramStarsConfig(
                provider_token=self.get('TELEGRAM_STARS_PROVIDER_TOKEN'),
                enabled=self.get('TELEGRAM_STARS_ENABLED', True)
            )
            
            # Database configuration
            database_config = DatabaseConfig(
                host=self.get('DB_HOST', 'localhost'),
                port=self.get('DB_PORT', 5432),
                name=self.get('DB_NAME'),
                user=self.get('DB_USER'),
                password=self.get('DB_PASSWORD'),
                url=self.get('DB_URL'),
                sqlite_path=self.get('SQLITE_DB_PATH')
            )
            
            # Admin configuration
            admin_config = AdminConfig(
                username=self.get('ADMIN_USERNAME'),
                password_hash=self.get('ADMIN_PASSWORD_HASH'),
                secret_key=self.get('ADMIN_SECRET_KEY'),
                session_expire_hours=self.get('ADMIN_SESSION_EXPIRE_HOURS', 24)
            )
            
            # Proxy servers configuration
            regions = self.get_list('REGIONS', default=['US', 'EU', 'ASIA', 'RU'])
            proxy_servers = {}
            
            for region in regions:
                proxy_servers[region] = ProxyServerConfig(
                    host=self.get(f'{region}_PROXY_HOST'),
                    port=self.get(f'{region}_PROXY_PORT', 8080),
                    username_prefix=self.get(f'{region}_PROXY_USERNAME'),
                    password_prefix=self.get(f'{region}_PROXY_PASSWORD')
                )
            
            # Subscription configuration
            subscription_config = SubscriptionConfig(
                monthly_price=self.get('MONTHLY_PLAN_PRICE', 9.99),
                quarterly_price=self.get('QUARTERLY_PLAN_PRICE', 24.99),
                yearly_price=self.get('YEARLY_PLAN_PRICE', 89.99),
                trial_days=self.get('TRIAL_DAYS', 7),
                trial_enabled=self.get('TRIAL_ENABLED', True),
                referral_commission_percent=self.get('REFERRAL_COMMISSION_PERCENT', 20),
                minimum_payout_usd=self.get('MINIMUM_PAYOUT_USD', 50.0)
            )
            
            # Observer configuration
            reminder_days = self.get_list('REMINDER_DAYS_BEFORE_EXPIRY', default=[7, 1])
            observer_config = ObserverConfig(
                check_interval_minutes=self.get('OBSERVER_CHECK_INTERVAL_MINUTES', 10),
                reminder_days=[int(day) for day in reminder_days],
                admin_alert_chat_id=self.get('ADMIN_ALERT_CHAT_ID')
            )
            
            # Security configuration
            security_config = SecurityConfig(
                encryption_key=self.get('ENCRYPTION_KEY'),
                rate_limit_requests_per_minute=self.get('RATE_LIMIT_REQUESTS_PER_MINUTE', 30),
                rate_limit_burst=self.get('RATE_LIMIT_BURST', 10)
            )
            
            return BotConfig(
                telegram=telegram_config,
                ton=ton_config,
                telegram_stars=telegram_stars_config,
                database=database_config,
                admin=admin_config,
                proxy_servers=proxy_servers,
                subscription=subscription_config,
                observer=observer_config,
                security=security_config,
                debug_mode=self.get('DEBUG_MODE', False),
                log_level=self.get('LOG_LEVEL', 'INFO')
            )
            
        except Exception as e:
            raise ValueError(f"Error parsing configuration: {e}")


# Global configuration instance
_config_parser: Optional[ConfigParser] = None
_bot_config: Optional[BotConfig] = None


def get_config(config_path: str = None) -> BotConfig:
    """Get the global bot configuration instance."""
    global _config_parser, _bot_config
    
    if _bot_config is None:
        if config_path is None:
            config_path = os.getenv('CONFIG_PATH', 'config/config.md')
        
        _config_parser = ConfigParser(config_path)
        _bot_config = _config_parser.parse_config()
    
    return _bot_config


def reload_config(config_path: str = None) -> BotConfig:
    """Reload configuration from file."""
    global _config_parser, _bot_config
    
    _config_parser = None
    _bot_config = None
    
    return get_config(config_path)


if __name__ == "__main__":
    # Test configuration parsing
    try:
        config = get_config()
        print("Configuration loaded successfully!")
        print(f"Bot Token: {config.telegram.bot_token[:10]}...")
        print(f"Database: {config.database.name}")
        print(f"TON Wallet: {config.ton.wallet_address}")
        print(f"Regions: {list(config.proxy_servers.keys())}")
    except Exception as e:
        print(f"Configuration error: {e}")
