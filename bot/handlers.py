"""
Complete Telegram bot handlers for Turbo Ping Bot.
Handles all user interactions including payments, subscriptions, referrals, and proxy access.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.orm import Session

from .models import (
    User, Subscription, SubscriptionPlan, Payment, PaymentStatus, 
    PaymentMethod, ProxyCredential, Referral, ReferralPayout, 
    BotMessage, DatabaseManager
)
from .payments import PaymentManager, PaymentError
from .config_parser import BotConfig
from .proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

# FSM States
class PaymentStates(StatesGroup):
    choosing_plan = State()
    choosing_payment_method = State()
    processing_payment = State()


class ReferralStates(StatesGroup):
    viewing_stats = State()
    requesting_payout = State()


class RegionStates(StatesGroup):
    choosing_region = State()


# Router for handlers
router = Router()


class BotHandlers:
    """Main bot handlers class."""
    
    def __init__(self, config: BotConfig, payment_manager: PaymentManager, 
                 proxy_manager: ProxyManager, db_session: Session):
        self.config = config
        self.payment_manager = payment_manager
        self.proxy_manager = proxy_manager
        self.db_session = db_session
        self.db_manager = DatabaseManager(db_session)
    
    def get_main_menu_keyboard(self) -> ReplyKeyboardMarkup:
        """Get main menu keyboard."""
        keyboard = [
            [KeyboardButton(text="💳 Оплатить подписку")],
            [KeyboardButton(text="🎁 Активировать пробный период")],
            [KeyboardButton(text="🔑 Получить доступы к прокси")],
            [KeyboardButton(text="🌍 Смена региона")],
            [KeyboardButton(text="📋 Инструкции")],
            [KeyboardButton(text="👥 Реферальная программа")],
            [KeyboardButton(text="🆘 Поддержка")]
        ]
        return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    
    def get_subscription_plans_keyboard(self) -> InlineKeyboardMarkup:
        """Get subscription plans keyboard."""
        builder = InlineKeyboardBuilder()
        
        plans = self.db_session.query(SubscriptionPlan).filter(
            SubscriptionPlan.is_active == True
        ).all()
        
        for plan in plans:
            builder.button(
                text=f"{plan.name} - ${plan.price_usd}",
                callback_data=f"plan_{plan.id}"
            )
        
        builder.button(text="◀️ Назад", callback_data="back_to_menu")
        builder.adjust(1)
        
        return builder.as_markup()
    
    def get_payment_methods_keyboard(self, plan_id: int) -> InlineKeyboardMarkup:
        """Get payment methods keyboard."""
        builder = InlineKeyboardBuilder()
        
        # TON payment (primary)
        builder.button(
            text="💎 TON (Рекомендуется)",
            callback_data=f"pay_ton_{plan_id}"
        )
        
        # Telegram Stars (if enabled)
        if self.config.telegram_stars.enabled:
            builder.button(
                text="⭐ Telegram Stars",
                callback_data=f"pay_stars_{plan_id}"
            )
        
        # Backup crypto options
        builder.button(
            text="💰 Другие криптовалюты",
            callback_data=f"pay_crypto_{plan_id}"
        )
        
        builder.button(text="◀️ Назад", callback_data="back_to_plans")
        builder.adjust(1)
        
        return builder.as_markup()
    
    def get_regions_keyboard(self) -> InlineKeyboardMarkup:
        """Get regions selection keyboard."""
        builder = InlineKeyboardBuilder()
        
        regions = {
            "US": "🇺🇸 США",
            "EU": "🇪🇺 Европа", 
            "ASIA": "🇯🇵 Азия",
            "RU": "🇷🇺 Россия"
        }
        
        for region_code, region_name in regions.items():
            builder.button(
                text=region_name,
                callback_data=f"region_{region_code}"
            )
        
        builder.button(text="◀️ Назад", callback_data="back_to_menu")
        builder.adjust(2)
        
        return builder.as_markup()
    
    def get_referral_menu_keyboard(self) -> InlineKeyboardMarkup:
        """Get referral program menu keyboard."""
        builder = InlineKeyboardBuilder()
        
        builder.button(text="📊 Статистика", callback_data="referral_stats")
        builder.button(text="💸 Заказ выплаты", callback_data="referral_payout")
        builder.button(text="◀️ Назад", callback_data="back_to_menu")
        builder.adjust(1)
        
        return builder.as_markup()


# Complete referral payout handler
@router.callback_query(F.data == "referral_payout")
async def handle_referral_payout(callback: CallbackQuery, handlers: BotHandlers):
    """Handle referral payout request."""
    try:
        user = handlers.db_manager.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("❌ Пользователь не найден.")
            return
        
        unpaid_earnings = user.get_unpaid_referral_earnings()
        min_payout = handlers.config.subscription.minimum_payout_usd
        
        if unpaid_earnings < min_payout:
            await callback.message.edit_text(
                f"❌ **Недостаточно средств для выплаты**\n\n"
                f"💰 **Доступно:** ${unpaid_earnings:.2f}\n"
                f"💸 **Минимум для вывода:** ${min_payout}\n"
                f"📈 **Нужно еще:** ${min_payout - unpaid_earnings:.2f}\n\n"
                f"Продолжайте приглашать друзей!",
                parse_mode="Markdown",
                reply_markup=handlers.get_referral_menu_keyboard()
            )
            await callback.answer()
            return
        
        # Create payout request
        payout = ReferralPayout(
            user_id=user.id,
            amount_usd=unpaid_earnings
        )
        handlers.db_session.add(payout)
        handlers.db_session.commit()
        
        payout_text = (
            f"💸 **Заявка на выплату создана**\n\n"
            f"💰 **Сумма:** ${unpaid_earnings:.2f}\n"
            f"📅 **Дата заявки:** {payout.requested_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"📋 **ID заявки:** {payout.id}\n\n"
            f"📞 **Для обработки выплаты обратитесь к администратору:**\n"
            f"👤 @turbo_ping_support\n\n"
            f"📝 **Укажите ID заявки:** `{payout.id}`\n"
            f"💳 **Способы выплаты:** TON, USDT\n\n"
            f"⏰ **Время обработки:** 1-3 рабочих дня"
        )
        
        await callback.message.edit_text(
            payout_text,
            parse_mode="Markdown",
            reply_markup=handlers.get_referral_menu_keyboard()
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Referral payout failed: {e}")
        await callback.answer("❌ Произошла ошибка.")


# Navigation callbacks
@router.callback_query(F.data == "back_to_menu")
async def handle_back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Handle back to main menu."""
    await state.clear()
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "back_to_plans")
async def handle_back_to_plans(callback: CallbackQuery, state: FSMContext,
                              handlers: BotHandlers):
    """Handle back to plans selection."""
    await state.set_state(PaymentStates.choosing_plan)
    
    await callback.message.edit_text(
        "💳 Выберите план подписки:",
        reply_markup=handlers.get_subscription_plans_keyboard()
    )
    
    await callback.answer()


# Admin commands (for testing and management)
@router.message(Command("admin"))
async def cmd_admin(message: Message, handlers: BotHandlers):
    """Handle admin command (for authorized users only)."""
    try:
        user = handlers.db_manager.get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            await message.answer("❌ Доступ запрещен.")
            return
        
        # Admin menu
        admin_text = (
            "👨‍💼 **Панель администратора**\n\n"
            "Доступные команды:\n"
            "• /grant_trial <user_id> <days> - Выдать пробный период\n"
            "• /extend_sub <user_id> <days> - Продлить подписку\n"
            "• /user_info <user_id> - Информация о пользователе\n"
            "• /stats - Общая статистика\n\n"
            "🌐 **Веб-панель:** http://localhost:8000/admin"
        )
        
        await message.answer(admin_text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Admin command failed: {e}")
        await message.answer("❌ Произошла ошибка.")


@router.message(Command("grant_trial"))
async def cmd_grant_trial(message: Message, handlers: BotHandlers):
    """Grant trial period to user."""
    try:
        user = handlers.db_manager.get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            await message.answer("❌ Доступ запрещен.")
            return
        
        args = message.text.split()
        if len(args) != 3:
            await message.answer("❌ Использование: /grant_trial <user_id> <days>")
            return
        
        target_user_id = int(args[1])
        trial_days = int(args[2])
        
        target_user = handlers.db_session.query(User).filter(
            User.telegram_id == target_user_id
        ).first()
        
        if not target_user:
            await message.answer("❌ Пользователь не найден.")
            return
        
        # Check if user already has active subscription
        active_sub = target_user.get_active_subscription()
        if active_sub:
            await message.answer("❌ У пользователя уже есть активная подписка.")
            return
        
        # Create trial subscription
        trial_plan = handlers.db_session.query(SubscriptionPlan).first()  # Use first available plan
        if not trial_plan:
            await message.answer("❌ План подписки не найден.")
            return
        
        subscription = handlers.db_manager.create_subscription(
            user_id=target_user.id,
            plan_id=trial_plan.id,
            is_trial=True,
            trial_days=trial_days
        )
        
        await message.answer(
            f"✅ Пробный период на {trial_days} дней выдан пользователю {target_user_id}"
        )
        
        # Notify user
        try:
            await message.bot.send_message(
                target_user_id,
                f"🎁 Вам выдан пробный период на {trial_days} дней!\n\n"
                f"Используйте команду '🔑 Получить доступы к прокси' для получения доступов."
            )
        except:
            pass  # User might have blocked the bot
        
    except Exception as e:
        logger.error(f"Grant trial failed: {e}")
        await message.answer("❌ Произошла ошибка.")


@router.message(Command("stats"))
async def cmd_stats(message: Message, handlers: BotHandlers):
    """Show bot statistics."""
    try:
        user = handlers.db_manager.get_user_by_telegram_id(message.from_user.id)
        if not user or not user.is_admin:
            await message.answer("❌ Доступ запрещен.")
            return
        
        # Get statistics
        total_users = handlers.db_session.query(User).count()
        active_subscriptions = handlers.db_session.query(Subscription).filter(
            Subscription.status == "active"
        ).count()
        total_payments = handlers.db_session.query(Payment).filter(
            Payment.status == "completed"
        ).count()
        total_revenue = handlers.db_session.query(Payment).filter(
            Payment.status == "completed"
        ).with_entities(Payment.amount_usd).all()
        
        revenue_sum = sum(float(payment[0]) for payment in total_revenue)
        
        stats_text = (
            f"📊 **Статистика бота**\n\n"
            f"👥 **Всего пользователей:** {total_users}\n"
            f"✅ **Активных подписок:** {active_subscriptions}\n"
            f"💳 **Завершенных платежей:** {total_payments}\n"
            f"💰 **Общая выручка:** ${revenue_sum:.2f}\n\n"
            f"📅 **Обновлено:** {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        
        await message.answer(stats_text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Stats command failed: {e}")
        await message.answer("❌ Произошла ошибка.")


# Error handler
@router.message()
async def handle_unknown_message(message: Message):
    """Handle unknown messages."""
    await message.answer(
        "❓ Неизвестная команда. Используйте меню для навигации.",
        reply_markup=BotHandlers(None, None, None, None).get_main_menu_keyboard()
    )
