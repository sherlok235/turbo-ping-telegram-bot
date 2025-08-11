"""
Observer service for Turbo Ping Bot.
Handles subscription expiry checks, reminders, and access revocation.
"""

import asyncio
import logging
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Add parent directory to path for imports
sys.path.append('/app')

from bot.config_parser import get_config, BotConfig
from bot.models import (
    User, Subscription, SubscriptionStatus, ProxyCredential, 
    ObserverLog, DatabaseManager
)
from bot.proxy_manager import ProxyManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/observer.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class ObserverService:
    """Observer service for monitoring subscriptions and sending reminders."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.bot: Bot = None
        self.db_engine = None
        self.db_session_factory = None
        self.proxy_manager: ProxyManager = None
        self.running = False
        
    async def initialize(self):
        """Initialize observer service."""
        try:
            # Initialize database
            self.db_engine = create_engine(
                self.config.database.url,
                echo=self.config.debug_mode,
                pool_pre_ping=True,
                pool_recycle=3600
            )
            
            self.db_session_factory = sessionmaker(
                bind=self.db_engine,
                expire_on_commit=False
            )
            
            # Initialize bot for sending messages
            self.bot = Bot(
                token=self.config.telegram.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML)
            )
            
            # Initialize proxy manager
            db_session = self.db_session_factory()
            self.proxy_manager = ProxyManager(self.config, db_session)
            
            logger.info("Observer service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize observer service: {e}")
            raise
    
    async def start(self):
        """Start the observer service."""
        self.running = True
        logger.info("Observer service started")
        
        try:
            while self.running:
                await self._run_checks()
                
                # Wait for next check interval
                await asyncio.sleep(self.config.observer.check_interval_minutes * 60)
                
        except Exception as e:
            logger.error(f"Observer service error: {e}")
        finally:
            await self.cleanup()
    
    def stop(self):
        """Stop the observer service."""
        self.running = False
        logger.info("Observer service stop requested")
    
    async def _run_checks(self):
        """Run all scheduled checks."""
        start_time = datetime.utcnow()
        logger.info("Starting scheduled checks")
        
        try:
            # Check for expiring subscriptions and send reminders
            await self._check_expiring_subscriptions()
            
            # Check for expired subscriptions and revoke access
            await self._check_expired_subscriptions()
            
            # Cleanup expired credentials
            await self._cleanup_expired_credentials()
            
            # Log successful execution
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            await self._log_observer_action(
                task_type="scheduled_check",
                status="success",
                message=f"Completed all checks in {execution_time:.0f}ms"
            )
            
        except Exception as e:
            logger.error(f"Scheduled checks failed: {e}")
            await self._log_observer_action(
                task_type="scheduled_check",
                status="failed",
                message=str(e)
            )
            
            # Send alert to admin
            await self._send_admin_alert(f"Observer service error: {e}")
    
    async def _check_expiring_subscriptions(self):
        """Check for subscriptions expiring soon and send reminders."""
        try:
            with self.db_session_factory() as session:
                db_manager = DatabaseManager(session)
                
                for days_before in self.config.observer.reminder_days:
                    expiring_subs = db_manager.get_expiring_subscriptions(days_before)
                    
                    for subscription in expiring_subs:
                        await self._send_expiry_reminder(subscription, days_before)
                        
                        # Log reminder sent
                        await self._log_observer_action(
                            task_type="reminder",
                            user_id=subscription.user_id,
                            subscription_id=subscription.id,
                            status="success",
                            message=f"Sent {days_before}-day reminder"
                        )
                
                logger.info(f"Processed expiry reminders for {len(self.config.observer.reminder_days)} reminder periods")
                
        except Exception as e:
            logger.error(f"Failed to check expiring subscriptions: {e}")
            raise
    
    async def _check_expired_subscriptions(self):
        """Check for expired subscriptions and revoke access."""
        try:
            with self.db_session_factory() as session:
                db_manager = DatabaseManager(session)
                expired_subs = db_manager.get_expired_subscriptions()
                
                revoked_count = 0
                
                for subscription in expired_subs:
                    try:
                        # Update subscription status
                        subscription.status = SubscriptionStatus.EXPIRED.value
                        
                        # Revoke proxy credentials
                        success = await self.proxy_manager.revoke_user_credentials(
                            subscription.user_id
                        )
                        
                        if success:
                            revoked_count += 1
                            
                            # Send expiry notification
                            await self._send_expiry_notification(subscription)
                            
                            # Log revocation
                            await self._log_observer_action(
                                task_type="revocation",
                                user_id=subscription.user_id,
                                subscription_id=subscription.id,
                                status="success",
                                message="Access revoked due to expiry"
                            )
                        else:
                            await self._log_observer_action(
                                task_type="revocation",
                                user_id=subscription.user_id,
                                subscription_id=subscription.id,
                                status="failed",
                                message="Failed to revoke proxy credentials"
                            )
                    
                    except Exception as e:
                        logger.error(f"Failed to process expired subscription {subscription.id}: {e}")
                        await self._log_observer_action(
                            task_type="revocation",
                            user_id=subscription.user_id,
                            subscription_id=subscription.id,
                            status="failed",
                            message=str(e)
                        )
                
                session.commit()
                logger.info(f"Processed {len(expired_subs)} expired subscriptions, revoked {revoked_count} accesses")
                
        except Exception as e:
            logger.error(f"Failed to check expired subscriptions: {e}")
            raise
    
    async def _cleanup_expired_credentials(self):
        """Clean up expired proxy credentials."""
        try:
            cleaned_count = await self.proxy_manager.cleanup_expired_credentials()
            
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} expired credentials")
                await self._log_observer_action(
                    task_type="cleanup",
                    status="success",
                    message=f"Cleaned up {cleaned_count} expired credentials"
                )
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired credentials: {e}")
            await self._log_observer_action(
                task_type="cleanup",
                status="failed",
                message=str(e)
            )
    
    async def _send_expiry_reminder(self, subscription: Subscription, days_before: int):
        """Send expiry reminder to user."""
        try:
            user = subscription.user
            
            if days_before == 1:
                message = (
                    f"⚠️ <b>Внимание!</b>\n\n"
                    f"Ваша подписка истекает завтра ({subscription.end_date.strftime('%d.%m.%Y %H:%M')}).\n\n"
                    f"💳 Продлите подписку, чтобы не потерять доступ к прокси.\n"
                    f"Используйте команду '💳 Оплатить подписку' для продления."
                )
            else:
                message = (
                    f"📅 <b>Напоминание о подписке</b>\n\n"
                    f"Ваша подписка истекает через {days_before} дней ({subscription.end_date.strftime('%d.%m.%Y %H:%M')}).\n\n"
                    f"💳 Не забудьте продлить подписку для продолжения использования прокси.\n"
                    f"Используйте команду '💳 Оплатить подписку' для продления."
                )
            
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=message
            )
            
            logger.info(f"Sent {days_before}-day reminder to user {user.telegram_id}")
            
        except Exception as e:
            logger.error(f"Failed to send expiry reminder to user {subscription.user_id}: {e}")
    
    async def _send_expiry_notification(self, subscription: Subscription):
        """Send expiry notification to user."""
        try:
            user = subscription.user
            
            message = (
                f"❌ <b>Подписка истекла</b>\n\n"
                f"Ваша подписка истекла {subscription.end_date.strftime('%d.%m.%Y %H:%M')}.\n\n"
                f"🔒 Доступ к прокси заблокирован.\n\n"
                f"💳 Для восстановления доступа оплатите новую подписку.\n"
                f"Используйте команду '💳 Оплатить подписку'."
            )
            
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=message
            )
            
            logger.info(f"Sent expiry notification to user {user.telegram_id}")
            
        except Exception as e:
            logger.error(f"Failed to send expiry notification to user {subscription.user_id}: {e}")
    
    async def _send_admin_alert(self, message: str):
        """Send alert to admin."""
        try:
            admin_chat_id = self.config.observer.admin_alert_chat_id
            if admin_chat_id:
                alert_message = (
                    f"🚨 <b>Observer Service Alert</b>\n\n"
                    f"<code>{message}</code>\n\n"
                    f"🕐 Time: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC"
                )
                
                await self.bot.send_message(
                    chat_id=admin_chat_id,
                    text=alert_message
                )
                
                logger.info(f"Sent admin alert: {message}")
            
        except Exception as e:
            logger.error(f"Failed to send admin alert: {e}")
    
    async def _log_observer_action(self, task_type: str, status: str, message: str = None,
                                 user_id: int = None, subscription_id: int = None,
                                 execution_time_ms: int = None):
        """Log observer action to database."""
        try:
            with self.db_session_factory() as session:
                log_entry = ObserverLog(
                    task_type=task_type,
                    user_id=user_id,
                    subscription_id=subscription_id,
                    status=status,
                    message=message,
                    execution_time_ms=execution_time_ms
                )
                
                session.add(log_entry)
                session.commit()
                
        except Exception as e:
            logger.error(f"Failed to log observer action: {e}")
    
    async def get_service_stats(self) -> Dict[str, Any]:
        """Get observer service statistics."""
        try:
            with self.db_session_factory() as session:
                # Get recent logs
                recent_logs = session.query(ObserverLog).filter(
                    ObserverLog.created_at >= datetime.utcnow() - timedelta(hours=24)
                ).all()
                
                # Count by status
                success_count = len([log for log in recent_logs if log.status == "success"])
                failed_count = len([log for log in recent_logs if log.status == "failed"])
                
                # Count by task type
                task_counts = {}
                for log in recent_logs:
                    task_counts[log.task_type] = task_counts.get(log.task_type, 0) + 1
                
                stats = {
                    "total_actions_24h": len(recent_logs),
                    "successful_actions": success_count,
                    "failed_actions": failed_count,
                    "task_breakdown": task_counts,
                    "last_check": max([log.created_at for log in recent_logs]) if recent_logs else None,
                    "service_uptime": datetime.utcnow().isoformat()
                }
                
                return stats
                
        except Exception as e:
            logger.error(f"Failed to get service stats: {e}")
            return {}
    
    async def cleanup(self):
        """Cleanup resources."""
        try:
            if self.bot:
                await self.bot.session.close()
            
            if self.db_engine:
                self.db_engine.dispose()
            
            logger.info("Observer service cleanup completed")
            
        except Exception as e:
            logger.error(f"Observer cleanup failed: {e}")


async def main():
    """Main observer service entry point."""
    try:
        # Load configuration
        config = get_config()
        
        # Create observer service
        observer = ObserverService(config)
        
        # Initialize service
        await observer.initialize()
        
        # Start service
        await observer.start()
        
    except KeyboardInterrupt:
        logger.info("Observer service stopped by user")
    except Exception as e:
        logger.error(f"Observer service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Run the observer service
    asyncio.run(main())
