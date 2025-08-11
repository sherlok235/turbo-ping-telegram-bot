"""
Payment integration system for Turbo Ping Bot.
Supports TON, Telegram Stars, and backup crypto payment providers.
"""

import asyncio
import hashlib
import hmac
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

import httpx
from aiogram import Bot
from aiogram.types import LabeledPrice, PreCheckoutQuery
from sqlalchemy.orm import Session

from .models import Payment, PaymentStatus, PaymentMethod, User, Subscription
from .config_parser import BotConfig

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """Base payment error."""
    pass


class PaymentVerificationError(PaymentError):
    """Payment verification failed."""
    pass


class PaymentProviderError(PaymentError):
    """Payment provider error."""
    pass


class PaymentResult:
    """Payment processing result."""
    
    def __init__(self, success: bool, payment_id: str = None, 
                 transaction_hash: str = None, error_message: str = None,
                 provider_data: Dict[str, Any] = None):
        self.success = success
        self.payment_id = payment_id
        self.transaction_hash = transaction_hash
        self.error_message = error_message
        self.provider_data = provider_data or {}


class BasePaymentProvider(ABC):
    """Abstract base class for payment providers."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=30.0)
    
    @abstractmethod
    async def create_payment(self, user_id: int, amount_usd: Decimal, 
                           description: str, metadata: Dict[str, Any] = None) -> PaymentResult:
        """Create a new payment."""
        pass
    
    @abstractmethod
    async def verify_payment(self, payment_data: Dict[str, Any]) -> PaymentResult:
        """Verify payment completion."""
        pass
    
    @abstractmethod
    async def get_payment_status(self, payment_id: str) -> PaymentResult:
        """Get payment status."""
        pass
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


class TONPaymentProvider(BasePaymentProvider):
    """TON (The Open Network) payment provider."""
    
    def __init__(self, config: BotConfig):
        super().__init__(config)
        self.wallet_address = config.ton.wallet_address
        self.api_endpoint = config.ton.api_endpoint
        self.api_key = config.ton.api_key
        self.network = config.ton.network
    
    async def create_payment(self, user_id: int, amount_usd: Decimal, 
                           description: str, metadata: Dict[str, Any] = None) -> PaymentResult:
        """Create TON payment request."""
        try:
            # Convert USD to TON (simplified - in production, use real exchange rate)
            ton_rate = await self._get_ton_usd_rate()
            amount_ton = amount_usd / ton_rate
            
            # Generate unique payment comment/memo
            payment_memo = f"TURBO_PING_{user_id}_{int(datetime.utcnow().timestamp())}"
            
            # Create payment URL for user
            payment_url = f"ton://transfer/{self.wallet_address}?amount={int(amount_ton * 1e9)}&text={payment_memo}"
            
            payment_data = {
                "wallet_address": self.wallet_address,
                "amount_ton": str(amount_ton),
                "amount_usd": str(amount_usd),
                "payment_memo": payment_memo,
                "payment_url": payment_url,
                "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat()
            }
            
            return PaymentResult(
                success=True,
                payment_id=payment_memo,
                provider_data=payment_data
            )
            
        except Exception as e:
            logger.error(f"TON payment creation failed: {e}")
            return PaymentResult(success=False, error_message=str(e))
    
    async def verify_payment(self, payment_data: Dict[str, Any]) -> PaymentResult:
        """Verify TON payment by checking blockchain transactions."""
        try:
            payment_memo = payment_data.get("payment_memo")
            expected_amount = Decimal(payment_data.get("amount_ton", "0"))
            
            # Get recent transactions for wallet
            transactions = await self._get_wallet_transactions()
            
            for tx in transactions:
                # Check if transaction matches our payment
                if (tx.get("comment") == payment_memo and 
                    Decimal(tx.get("value", "0")) >= expected_amount):
                    
                    return PaymentResult(
                        success=True,
                        transaction_hash=tx.get("hash"),
                        provider_data=tx
                    )
            
            return PaymentResult(success=False, error_message="Payment not found on blockchain")
            
        except Exception as e:
            logger.error(f"TON payment verification failed: {e}")
            return PaymentResult(success=False, error_message=str(e))
    
    async def get_payment_status(self, payment_id: str) -> PaymentResult:
        """Get TON payment status."""
        try:
            # Check if payment exists in recent transactions
            transactions = await self._get_wallet_transactions()
            
            for tx in transactions:
                if tx.get("comment") == payment_id:
                    return PaymentResult(
                        success=True,
                        transaction_hash=tx.get("hash"),
                        provider_data=tx
                    )
            
            return PaymentResult(success=False, error_message="Payment not found")
            
        except Exception as e:
            logger.error(f"TON payment status check failed: {e}")
            return PaymentResult(success=False, error_message=str(e))
    
    async def _get_ton_usd_rate(self) -> Decimal:
        """Get current TON/USD exchange rate."""
        try:
            # Use a crypto API to get current rate (simplified)
            response = await self.client.get("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd")
            data = response.json()
            rate = Decimal(str(data["the-open-network"]["usd"]))
            return rate
        except Exception as e:
            logger.warning(f"Failed to get TON rate, using fallback: {e}")
            return Decimal("2.5")  # Fallback rate
    
    async def _get_wallet_transactions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent wallet transactions."""
        try:
            url = f"{self.api_endpoint}/getTransactions"
            params = {
                "address": self.wallet_address,
                "limit": limit,
                "api_key": self.api_key
            }
            
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get("result", [])
            
        except Exception as e:
            logger.error(f"Failed to get TON transactions: {e}")
            return []


class TelegramStarsProvider(BasePaymentProvider):
    """Telegram Stars payment provider."""
    
    def __init__(self, config: BotConfig, bot: Bot):
        super().__init__(config)
        self.bot = bot
        self.provider_token = config.telegram_stars.provider_token
        self.enabled = config.telegram_stars.enabled
    
    async def create_payment(self, user_id: int, amount_usd: Decimal, 
                           description: str, metadata: Dict[str, Any] = None) -> PaymentResult:
        """Create Telegram Stars payment."""
        try:
            if not self.enabled:
                return PaymentResult(success=False, error_message="Telegram Stars payments disabled")
            
            # Convert USD to Stars (1 Star ≈ $0.01, but this varies)
            stars_amount = int(amount_usd * 100)  # Simplified conversion
            
            # Create invoice
            prices = [LabeledPrice(label=description, amount=stars_amount)]
            
            payment_data = {
                "provider_token": self.provider_token,
                "currency": "XTR",  # Telegram Stars currency code
                "prices": [{"label": description, "amount": stars_amount}],
                "description": description,
                "payload": json.dumps({
                    "user_id": user_id,
                    "amount_usd": str(amount_usd),
                    "timestamp": int(datetime.utcnow().timestamp())
                })
            }
            
            return PaymentResult(
                success=True,
                payment_id=f"stars_{user_id}_{int(datetime.utcnow().timestamp())}",
                provider_data=payment_data
            )
            
        except Exception as e:
            logger.error(f"Telegram Stars payment creation failed: {e}")
            return PaymentResult(success=False, error_message=str(e))
    
    async def verify_payment(self, payment_data: Dict[str, Any]) -> PaymentResult:
        """Verify Telegram Stars payment."""
        try:
            # Telegram Stars payments are verified through pre_checkout_query
            # and successful_payment handlers in the bot
            charge_id = payment_data.get("telegram_payment_charge_id")
            
            if charge_id:
                return PaymentResult(
                    success=True,
                    transaction_hash=charge_id,
                    provider_data=payment_data
                )
            
            return PaymentResult(success=False, error_message="No charge ID provided")
            
        except Exception as e:
            logger.error(f"Telegram Stars payment verification failed: {e}")
            return PaymentResult(success=False, error_message=str(e))
    
    async def get_payment_status(self, payment_id: str) -> PaymentResult:
        """Get Telegram Stars payment status."""
        # Telegram doesn't provide API to check payment status after completion
        # Status is determined by successful_payment webhook
        return PaymentResult(success=False, error_message="Status check not available for Telegram Stars")


class NOWPaymentsProvider(BasePaymentProvider):
    """NOWPayments crypto payment provider (backup)."""
    
    def __init__(self, config: BotConfig):
        super().__init__(config)
        self.api_key = getattr(config, 'nowpayments_api_key', None)
        self.ipn_secret = getattr(config, 'nowpayments_ipn_secret', None)
        self.base_url = "https://api.nowpayments.io/v1"
    
    async def create_payment(self, user_id: int, amount_usd: Decimal, 
                           description: str, metadata: Dict[str, Any] = None) -> PaymentResult:
        """Create NOWPayments payment."""
        try:
            if not self.api_key:
                return PaymentResult(success=False, error_message="NOWPayments not configured")
            
            headers = {"x-api-key": self.api_key}
            payload = {
                "price_amount": float(amount_usd),
                "price_currency": "USD",
                "pay_currency": "USDT",  # Default to USDT
                "order_id": f"turbo_ping_{user_id}_{int(datetime.utcnow().timestamp())}",
                "order_description": description,
                "ipn_callback_url": f"{self.config.base_url}/webhooks/nowpayments",
                "success_url": f"{self.config.base_url}/payment/success",
                "cancel_url": f"{self.config.base_url}/payment/cancel"
            }
            
            response = await self.client.post(
                f"{self.base_url}/payment",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            
            data = response.json()
            
            return PaymentResult(
                success=True,
                payment_id=data.get("payment_id"),
                provider_data=data
            )
            
        except Exception as e:
            logger.error(f"NOWPayments payment creation failed: {e}")
            return PaymentResult(success=False, error_message=str(e))
    
    async def verify_payment(self, payment_data: Dict[str, Any]) -> PaymentResult:
        """Verify NOWPayments payment via IPN."""
        try:
            # Verify IPN signature
            if not self._verify_ipn_signature(payment_data):
                return PaymentResult(success=False, error_message="Invalid IPN signature")
            
            payment_status = payment_data.get("payment_status")
            if payment_status == "finished":
                return PaymentResult(
                    success=True,
                    transaction_hash=payment_data.get("payment_id"),
                    provider_data=payment_data
                )
            
            return PaymentResult(success=False, error_message=f"Payment status: {payment_status}")
            
        except Exception as e:
            logger.error(f"NOWPayments verification failed: {e}")
            return PaymentResult(success=False, error_message=str(e))
    
    async def get_payment_status(self, payment_id: str) -> PaymentResult:
        """Get NOWPayments payment status."""
        try:
            if not self.api_key:
                return PaymentResult(success=False, error_message="NOWPayments not configured")
            
            headers = {"x-api-key": self.api_key}
            response = await self.client.get(
                f"{self.base_url}/payment/{payment_id}",
                headers=headers
            )
            response.raise_for_status()
            
            data = response.json()
            payment_status = data.get("payment_status")
            
            return PaymentResult(
                success=payment_status == "finished",
                provider_data=data
            )
            
        except Exception as e:
            logger.error(f"NOWPayments status check failed: {e}")
            return PaymentResult(success=False, error_message=str(e))
    
    def _verify_ipn_signature(self, payment_data: Dict[str, Any]) -> bool:
        """Verify NOWPayments IPN signature."""
        if not self.ipn_secret:
            return True  # Skip verification if secret not configured
        
        try:
            received_signature = payment_data.get("signature")
            if not received_signature:
                return False
            
            # Create expected signature
            sorted_data = sorted(payment_data.items())
            query_string = "&".join([f"{k}={v}" for k, v in sorted_data if k != "signature"])
            expected_signature = hmac.new(
                self.ipn_secret.encode(),
                query_string.encode(),
                hashlib.sha512
            ).hexdigest()
            
            return hmac.compare_digest(received_signature, expected_signature)
            
        except Exception as e:
            logger.error(f"IPN signature verification failed: {e}")
            return False


class PaymentManager:
    """Main payment manager coordinating all payment providers."""
    
    def __init__(self, config: BotConfig, bot: Bot, db_session: Session):
        self.config = config
        self.bot = bot
        self.db_session = db_session
        
        # Initialize payment providers
        self.providers = {
            PaymentMethod.TON: TONPaymentProvider(config),
            PaymentMethod.TELEGRAM_STARS: TelegramStarsProvider(config, bot),
            PaymentMethod.NOWPAYMENTS: NOWPaymentsProvider(config)
        }
        
        # Payment method priority (TON > Telegram Stars > Others)
        self.payment_priority = [
            PaymentMethod.TON,
            PaymentMethod.TELEGRAM_STARS,
            PaymentMethod.NOWPAYMENTS
        ]
    
    async def create_payment(self, user_id: int, amount_usd: Decimal, 
                           description: str, payment_method: PaymentMethod = None,
                           metadata: Dict[str, Any] = None) -> Tuple[Payment, PaymentResult]:
        """Create a new payment using specified or preferred method."""
        
        # Use specified method or first available from priority list
        if payment_method:
            methods_to_try = [payment_method]
        else:
            methods_to_try = self.payment_priority
        
        last_error = None
        
        for method in methods_to_try:
            provider = self.providers.get(method)
            if not provider:
                continue
            
            try:
                # Create payment record in database
                payment = Payment(
                    user_id=user_id,
                    payment_method=method.value,
                    amount_usd=amount_usd,
                    status=PaymentStatus.PENDING.value
                )
                self.db_session.add(payment)
                self.db_session.commit()
                
                # Create payment with provider
                result = await provider.create_payment(user_id, amount_usd, description, metadata)
                
                if result.success:
                    # Update payment record with provider data
                    payment.payment_provider_id = result.payment_id
                    payment.payment_data = result.provider_data
                    self.db_session.commit()
                    
                    return payment, result
                else:
                    # Mark payment as failed
                    payment.mark_failed()
                    self.db_session.commit()
                    last_error = result.error_message
                    
            except Exception as e:
                logger.error(f"Payment creation failed for {method}: {e}")
                last_error = str(e)
                continue
        
        # All methods failed
        raise PaymentError(f"All payment methods failed. Last error: {last_error}")
    
    async def verify_payment(self, payment: Payment) -> PaymentResult:
        """Verify payment completion."""
        method = PaymentMethod(payment.payment_method)
        provider = self.providers.get(method)
        
        if not provider:
            return PaymentResult(success=False, error_message=f"Provider not found for {method}")
        
        try:
            result = await provider.verify_payment(payment.payment_data or {})
            
            if result.success:
                # Update payment record
                payment.mark_completed()
                if result.transaction_hash:
                    if method == PaymentMethod.TON:
                        payment.ton_transaction_id = result.transaction_hash
                    elif method == PaymentMethod.TELEGRAM_STARS:
                        payment.telegram_payment_charge_id = result.transaction_hash
                    else:
                        payment.transaction_hash = result.transaction_hash
                
                self.db_session.commit()
                
                # Process referral commission if applicable
                await self._process_referral_commission(payment)
            
            return result
            
        except Exception as e:
            logger.error(f"Payment verification failed: {e}")
            return PaymentResult(success=False, error_message=str(e))
    
    async def get_payment_status(self, payment: Payment) -> PaymentResult:
        """Get current payment status."""
        method = PaymentMethod(payment.payment_method)
        provider = self.providers.get(method)
        
        if not provider:
            return PaymentResult(success=False, error_message=f"Provider not found for {method}")
        
        return await provider.get_payment_status(payment.payment_provider_id)
    
    async def _process_referral_commission(self, payment: Payment) -> None:
        """Process referral commission for completed payment."""
        try:
            user = self.db_session.query(User).filter(User.id == payment.user_id).first()
            if not user or not user.referred_by_user_id:
                return
            
            # Calculate commission
            commission_percent = self.config.subscription.referral_commission_percent
            commission_amount = payment.amount_usd * Decimal(commission_percent) / Decimal(100)
            
            # Find referral record
            from .models import Referral
            referral = self.db_session.query(Referral).filter(
                Referral.referrer_id == user.referred_by_user_id,
                Referral.referred_user_id == user.id
            ).first()
            
            if referral:
                referral.commission_amount_usd += commission_amount
                referral.payment_id = payment.id
                self.db_session.commit()
                
                logger.info(f"Processed referral commission: ${commission_amount} for user {user.referred_by_user_id}")
            
        except Exception as e:
            logger.error(f"Failed to process referral commission: {e}")
    
    async def close(self):
        """Close all payment providers."""
        for provider in self.providers.values():
            await provider.close()


# Telegram Stars payment handlers
async def handle_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, payment_manager: PaymentManager):
    """Handle Telegram Stars pre-checkout query."""
    try:
        # Verify the payment request
        payload_data = json.loads(pre_checkout_query.invoice_payload)
        user_id = payload_data.get("user_id")
        amount_usd = Decimal(payload_data.get("amount_usd", "0"))
        
        # Validate payment
        if user_id and amount_usd > 0:
            await pre_checkout_query.answer(ok=True)
        else:
            await pre_checkout_query.answer(ok=False, error_message="Invalid payment data")
            
    except Exception as e:
        logger.error(f"Pre-checkout query failed: {e}")
        await pre_checkout_query.answer(ok=False, error_message="Payment validation failed")


async def handle_successful_payment(message, payment_manager: PaymentManager):
    """Handle successful Telegram Stars payment."""
    try:
        payment_info = message.successful_payment
        payload_data = json.loads(payment_info.invoice_payload)
        
        user_id = payload_data.get("user_id")
        charge_id = payment_info.telegram_payment_charge_id
        
        # Find pending payment
        payment = payment_manager.db_session.query(Payment).filter(
            Payment.user_id == user_id,
            Payment.payment_method == PaymentMethod.TELEGRAM_STARS.value,
            Payment.status == PaymentStatus.PENDING.value
        ).order_by(Payment.created_at.desc()).first()
        
        if payment:
            # Verify and complete payment
            payment_data = {"telegram_payment_charge_id": charge_id}
            result = await payment_manager.verify_payment(payment)
            
            if result.success:
                await message.answer("✅ Оплата успешно завершена! Ваша подписка активирована.")
            else:
                await message.answer("❌ Ошибка при обработке платежа. Обратитесь в поддержку.")
        else:
            await message.answer("❌ Платеж не найден. Обратитесь в поддержку.")
            
    except Exception as e:
        logger.error(f"Successful payment handling failed: {e}")
        await message.answer("❌ Ошибка при обработке платежа. Обратитесь в поддержку.")
