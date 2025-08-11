"""
Main Turbo Ping Telegram Bot application.
"""

import asyncio
import logging
import sys
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config_parser import get_config, BotConfig
from .models import Base, User
from .handlers import router, BotHandlers
from .payments import PaymentManager
from .proxy_manager import ProxyManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class TurboPingBot:
    """Main bot application class."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.bot: Optional[Bot] = None
        self.dp: Optional[Dispatcher] = None
        self.db_engine = None
        self.db_session_factory = None
        self.payment_manager: Optional[PaymentManager] = None
        self.proxy_manager: Optional[ProxyManager] = None
        self.handlers: Optional[BotHandlers] = None
        
    async def initialize(self):
        """Initialize bot components."""
        try:
            # Initialize database
            await self._init_database()
            
            # Initialize bot and dispatcher
            await self._init_bot()
            
            # Initialize managers
            await self._init_managers()
            
            # Setup handlers
            await self._setup_handlers()
            
            # Set bot commands
            await self._set_bot_commands()
            
            logger.info("Bot initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            raise
    
    async def _init_database(self):
        """Initialize database connection and tables."""
        try:
            # Create database engine
            self.db_engine = create_engine(
                self.config.database.url,
                echo=self.config.debug_mode,
                pool_pre_ping=True,
                pool_recycle=3600
            )
            
            # Create tables
            Base.metadata.create_all(self.db_engine)
            
            # Create session factory
            self.db_session_factory = sessionmaker(
                bind=self.db_engine,
                expire_on_commit=False
            )
            
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    async def _init_bot(self):
        """Initialize bot and dispatcher."""
        try:
            # Create bot instance
            self.bot = Bot(
                token=self.config.telegram.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML)
            )
            
            # Create dispatcher with memory storage
            storage = MemoryStorage()
            self.dp = Dispatcher(storage=storage)
            
            logger.info("Bot and dispatcher initialized")
            
        except Exception as e:
            logger.error(f"Bot initialization failed: {e}")
            raise
    
    async def _init_managers(self):
        """Initialize payment and proxy managers."""
        try:
            # Create database session
            db_session = self.db_session_factory()
            
            # Initialize payment manager
            self.payment_manager = PaymentManager(
                config=self.config,
                bot=self.bot,
                db_session=db_session
            )
            
            # Initialize proxy manager
            self.proxy_manager = ProxyManager(
                config=self.config,
                db_session=db_session
            )
            
            # Initialize handlers
            self.handlers = BotHandlers(
                config=self.config,
                payment_manager=self.payment_manager,
                proxy_manager=self.proxy_manager,
                db_session=db_session
            )
            
            logger.info("Managers initialized successfully")
            
        except Exception as e:
            logger.error(f"Managers initialization failed: {e}")
            raise
    
    async def _setup_handlers(self):
        """Setup bot handlers."""
        try:
            # Include main router
            self.dp.include_router(router)
            
            # Inject dependencies into handlers
            @self.dp.message.middleware()
            async def inject_dependencies(handler, event, data):
                data['handlers'] = self.handlers
                return await handler(event, **data)
            
            @self.dp.callback_query.middleware()
            async def inject_dependencies_callback(handler, event, data):
                data['handlers'] = self.handlers
                return await handler(event, **data)
            
            logger.info("Handlers setup completed")
            
        except Exception as e:
            logger.error(f"Handlers setup failed: {e}")
            raise
    
    async def _set_bot_commands(self):
        """Set bot commands menu."""
        try:
            commands = [
                BotCommand(command="start", description="🚀 Запустить бота"),
                BotCommand(command="admin", description="👨‍💼 Админ панель"),
                BotCommand(command="stats", description="📊 Статистика"),
            ]
            
            await self.bot.set_my_commands(commands)
            logger.info("Bot commands set successfully")
            
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")
    
    async def start_polling(self):
        """Start bot in polling mode."""
        try:
            logger.info("Starting bot in polling mode...")
            await self.dp.start_polling(self.bot)
            
        except Exception as e:
            logger.error(f"Polling failed: {e}")
            raise
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """Cleanup resources."""
        try:
            if self.payment_manager:
                await self.payment_manager.close()
            
            if self.bot:
                await self.bot.session.close()
            
            if self.db_engine:
                self.db_engine.dispose()
            
            logger.info("Cleanup completed")
            
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")


async def main():
    """Main application entry point."""
    try:
        # Load configuration
        config = get_config()
        
        # Create bot instance
        bot_app = TurboPingBot(config)
        
        # Initialize bot
        await bot_app.initialize()
        
        # Start bot in polling mode
        await bot_app.start_polling()
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Run the bot
    asyncio.run(main())
