"""
Proxy credential management system for Turbo Ping Bot.
Handles assignment, encryption, and management of VPN/proxy credentials.
"""

import logging
import secrets
import string
from typing import Optional, Dict, List
from datetime import datetime

from sqlalchemy.orm import Session
from cryptography.fernet import Fernet

from .models import ProxyCredential, User, EncryptionMixin
from .config_parser import BotConfig

logger = logging.getLogger(__name__)


class ProxyManager(EncryptionMixin):
    """Manager for proxy credentials and server assignments."""
    
    def __init__(self, config: BotConfig, db_session: Session):
        self.config = config
        self.db_session = db_session
        self.encryption_key = config.security.encryption_key
        
        # Validate encryption key
        try:
            Fernet(self.encryption_key.encode())
        except Exception as e:
            raise ValueError(f"Invalid encryption key: {e}")
    
    async def get_user_proxy_credentials(self, user_id: int, region: str) -> Optional[ProxyCredential]:
        """Get or create proxy credentials for user in specified region."""
        try:
            # Check if user already has active credentials for this region
            existing_creds = self.db_session.query(ProxyCredential).filter(
                ProxyCredential.user_id == user_id,
                ProxyCredential.region == region,
                ProxyCredential.is_active == True
            ).first()
            
            if existing_creds:
                logger.info(f"Found existing credentials for user {user_id} in region {region}")
                return existing_creds
            
            # Create new credentials
            return await self._create_proxy_credentials(user_id, region)
            
        except Exception as e:
            logger.error(f"Failed to get proxy credentials for user {user_id}: {e}")
            return None
    
    async def _create_proxy_credentials(self, user_id: int, region: str) -> Optional[ProxyCredential]:
        """Create new proxy credentials for user."""
        try:
            # Get server configuration for region
            server_config = self.config.proxy_servers.get(region)
            if not server_config:
                logger.error(f"No server configuration found for region {region}")
                return None
            
            # Generate unique username and password
            username = self._generate_proxy_username(user_id, region, server_config.username_prefix)
            password = self._generate_proxy_password()
            
            # Create proxy credential record
            proxy_creds = ProxyCredential(
                user_id=user_id,
                region=region,
                proxy_host=server_config.host,
                proxy_port=server_config.port
            )
            
            # Set encrypted credentials
            proxy_creds.set_credentials(username, password, self.encryption_key)
            
            # Save to database
            self.db_session.add(proxy_creds)
            self.db_session.commit()
            
            logger.info(f"Created new proxy credentials for user {user_id} in region {region}")
            return proxy_creds
            
        except Exception as e:
            logger.error(f"Failed to create proxy credentials: {e}")
            self.db_session.rollback()
            return None
    
    def _generate_proxy_username(self, user_id: int, region: str, prefix: str) -> str:
        """Generate unique proxy username."""
        # Format: prefix + user_id + region + random suffix
        random_suffix = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
        username = f"{prefix}{user_id}_{region.lower()}_{random_suffix}"
        return username[:32]  # Limit username length
    
    def _generate_proxy_password(self, length: int = 16) -> str:
        """Generate secure proxy password."""
        # Use mix of letters, digits, and safe special characters
        characters = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(characters) for _ in range(length))
        return password
    
    async def revoke_user_credentials(self, user_id: int, region: str = None) -> bool:
        """Revoke proxy credentials for user."""
        try:
            query = self.db_session.query(ProxyCredential).filter(
                ProxyCredential.user_id == user_id,
                ProxyCredential.is_active == True
            )
            
            if region:
                query = query.filter(ProxyCredential.region == region)
            
            credentials = query.all()
            
            for cred in credentials:
                cred.revoke()
            
            self.db_session.commit()
            
            logger.info(f"Revoked {len(credentials)} credentials for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to revoke credentials for user {user_id}: {e}")
            self.db_session.rollback()
            return False
    
    async def change_user_region(self, user_id: int, old_region: str, new_region: str) -> Optional[ProxyCredential]:
        """Change user's region and update proxy credentials."""
        try:
            # Revoke old credentials
            await self.revoke_user_credentials(user_id, old_region)
            
            # Create new credentials for new region
            new_creds = await self._create_proxy_credentials(user_id, new_region)
            
            if new_creds:
                logger.info(f"Changed region for user {user_id} from {old_region} to {new_region}")
            
            return new_creds
            
        except Exception as e:
            logger.error(f"Failed to change region for user {user_id}: {e}")
            return None
    
    def get_active_credentials_count(self, region: str = None) -> int:
        """Get count of active credentials."""
        try:
            query = self.db_session.query(ProxyCredential).filter(
                ProxyCredential.is_active == True
            )
            
            if region:
                query = query.filter(ProxyCredential.region == region)
            
            return query.count()
            
        except Exception as e:
            logger.error(f"Failed to get credentials count: {e}")
            return 0
    
    def get_region_statistics(self) -> Dict[str, int]:
        """Get statistics for each region."""
        try:
            stats = {}
            
            for region in self.config.proxy_servers.keys():
                count = self.get_active_credentials_count(region)
                stats[region] = count
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get region statistics: {e}")
            return {}
    
    async def cleanup_expired_credentials(self) -> int:
        """Clean up credentials for users with expired subscriptions."""
        try:
            # Get users with expired subscriptions
            from .models import Subscription, SubscriptionStatus
            
            expired_subscriptions = self.db_session.query(Subscription).filter(
                Subscription.status == SubscriptionStatus.ACTIVE.value,
                Subscription.end_date <= datetime.utcnow()
            ).all()
            
            revoked_count = 0
            
            for subscription in expired_subscriptions:
                # Revoke proxy credentials
                success = await self.revoke_user_credentials(subscription.user_id)
                if success:
                    revoked_count += 1
                
                # Update subscription status
                subscription.status = SubscriptionStatus.EXPIRED.value
            
            self.db_session.commit()
            
            logger.info(f"Cleaned up {revoked_count} expired credentials")
            return revoked_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired credentials: {e}")
            self.db_session.rollback()
            return 0
    
    def validate_proxy_server_config(self) -> Dict[str, bool]:
        """Validate proxy server configurations."""
        validation_results = {}
        
        for region, server_config in self.config.proxy_servers.items():
            try:
                # Basic validation
                is_valid = (
                    bool(server_config.host) and
                    isinstance(server_config.port, int) and
                    1 <= server_config.port <= 65535 and
                    bool(server_config.username_prefix) and
                    bool(server_config.password_prefix)
                )
                
                validation_results[region] = is_valid
                
                if not is_valid:
                    logger.warning(f"Invalid configuration for region {region}")
                
            except Exception as e:
                logger.error(f"Error validating config for region {region}: {e}")
                validation_results[region] = False
        
        return validation_results
    
    async def test_proxy_connectivity(self, region: str) -> bool:
        """Test connectivity to proxy server (basic check)."""
        try:
            import socket
            
            server_config = self.config.proxy_servers.get(region)
            if not server_config:
                return False
            
            # Test TCP connection
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)  # 5 second timeout
            
            result = sock.connect_ex((server_config.host, server_config.port))
            sock.close()
            
            is_reachable = result == 0
            
            if is_reachable:
                logger.info(f"Proxy server {region} is reachable")
            else:
                logger.warning(f"Proxy server {region} is not reachable")
            
            return is_reachable
            
        except Exception as e:
            logger.error(f"Failed to test connectivity for region {region}: {e}")
            return False
    
    def get_user_credentials_info(self, user_id: int) -> List[Dict]:
        """Get information about user's proxy credentials."""
        try:
            credentials = self.db_session.query(ProxyCredential).filter(
                ProxyCredential.user_id == user_id
            ).all()
            
            creds_info = []
            
            for cred in credentials:
                info = {
                    "id": cred.id,
                    "region": cred.region,
                    "host": cred.proxy_host,
                    "port": cred.proxy_port,
                    "is_active": cred.is_active,
                    "assigned_at": cred.assigned_at,
                    "revoked_at": cred.revoked_at
                }
                creds_info.append(info)
            
            return creds_info
            
        except Exception as e:
            logger.error(f"Failed to get credentials info for user {user_id}: {e}")
            return []
    
    async def rotate_user_credentials(self, user_id: int, region: str) -> Optional[ProxyCredential]:
        """Rotate (regenerate) user's proxy credentials."""
        try:
            # Revoke existing credentials
            await self.revoke_user_credentials(user_id, region)
            
            # Create new credentials
            new_creds = await self._create_proxy_credentials(user_id, region)
            
            if new_creds:
                logger.info(f"Rotated credentials for user {user_id} in region {region}")
            
            return new_creds
            
        except Exception as e:
            logger.error(f"Failed to rotate credentials for user {user_id}: {e}")
            return None
    
    def export_credentials_for_backup(self) -> List[Dict]:
        """Export all credentials for backup (without decryption)."""
        try:
            credentials = self.db_session.query(ProxyCredential).filter(
                ProxyCredential.is_active == True
            ).all()
            
            backup_data = []
            
            for cred in credentials:
                data = {
                    "user_id": cred.user_id,
                    "region": cred.region,
                    "host": cred.proxy_host,
                    "port": cred.proxy_port,
                    "assigned_at": cred.assigned_at.isoformat(),
                    # Note: Not including encrypted credentials for security
                }
                backup_data.append(data)
            
            logger.info(f"Exported {len(backup_data)} credentials for backup")
            return backup_data
            
        except Exception as e:
            logger.error(f"Failed to export credentials: {e}")
            return []


# Utility functions for proxy management
async def get_optimal_region_for_user(user_location: str = None) -> str:
    """Get optimal region based on user location (simplified)."""
    # This is a simplified implementation
    # In production, you might use GeoIP or user preference
    
    region_mapping = {
        "US": ["US", "CA", "MX"],
        "EU": ["GB", "DE", "FR", "IT", "ES", "NL", "SE", "NO"],
        "ASIA": ["JP", "KR", "SG", "HK", "TW"],
        "RU": ["RU", "BY", "KZ", "UA"]
    }
    
    if user_location:
        for region, countries in region_mapping.items():
            if user_location.upper() in countries:
                return region
    
    # Default to US if no match
    return "US"


def generate_proxy_config_file(credentials: ProxyCredential, encryption_key: str) -> str:
    """Generate proxy configuration file content."""
    try:
        username, password = credentials.get_credentials(encryption_key)
        
        config_content = f"""# Turbo Ping Proxy Configuration
# Region: {credentials.region}
# Generated: {datetime.utcnow().isoformat()}

[Proxy]
Type=HTTP
Host={credentials.proxy_host}
Port={credentials.proxy_port}
Username={username}
Password={password}

[Settings]
ConnectTimeout=30
ReadTimeout=60
"""
        
        return config_content
        
    except Exception as e:
        logger.error(f"Failed to generate config file: {e}")
        return ""


def validate_proxy_credentials_format(username: str, password: str) -> bool:
    """Validate proxy credentials format."""
    try:
        # Basic validation rules
        username_valid = (
            len(username) >= 4 and
            len(username) <= 32 and
            username.replace('_', '').replace('-', '').isalnum()
        )
        
        password_valid = (
            len(password) >= 8 and
            len(password) <= 64 and
            any(c.isupper() for c in password) and
            any(c.islower() for c in password) and
            any(c.isdigit() for c in password)
        )
        
        return username_valid and password_valid
        
    except Exception as e:
        logger.error(f"Failed to validate credentials format: {e}")
        return False
