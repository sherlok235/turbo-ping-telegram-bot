"""
Database models for Turbo Ping Telegram Bot.
Includes User, Subscription, Payment, Referral, and ProxyCredential models with encryption.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, DECIMAL, 
    ForeignKey, UniqueConstraint, Index, BigInteger, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Session
from sqlalchemy.sql import func
from cryptography.fernet import Fernet
import bcrypt
import secrets
import string

Base = declarative_base()


class PaymentMethod(str, Enum):
    TON = "ton"
    TELEGRAM_STARS = "telegram_stars"
    NOWPAYMENTS = "nowpayments"
    COINBASE = "coinbase"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    TRIAL = "trial"


class PayoutStatus(str, Enum):
    REQUESTED = "requested"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EncryptionMixin:
    """Mixin for handling field encryption/decryption."""
    
    @staticmethod
    def encrypt_data(data: str, encryption_key: str) -> str:
        """Encrypt sensitive data using Fernet."""
        if not data:
            return ""
        
        fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        return fernet.encrypt(data.encode()).decode()
    
    @staticmethod
    def decrypt_data(encrypted_data: str, encryption_key: str) -> str:
        """Decrypt sensitive data using Fernet."""
        if not encrypted_data:
            return ""
        
        fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        return fernet.decrypt(encrypted_data.encode()).decode()


class User(Base):
    """User model for storing Telegram user information."""
    
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    language_code = Column(String(10), default="en")
    referral_code = Column(String(50), unique=True, nullable=False, index=True)
    referred_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    region = Column(String(10), default="US")
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_activity = Column(DateTime, default=func.now())
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    referrals_made = relationship("Referral", foreign_keys="Referral.referrer_id", back_populates="referrer")
    referrals_received = relationship("Referral", foreign_keys="Referral.referred_user_id", back_populates="referred_user")
    proxy_credentials = relationship("ProxyCredential", back_populates="user", cascade="all, delete-orphan")
    referral_payouts = relationship("ReferralPayout", back_populates="user", cascade="all, delete-orphan")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.referral_code:
            self.referral_code = self.generate_referral_code()
    
    @staticmethod
    def generate_referral_code(length: int = 8) -> str:
        """Generate a unique referral code."""
        characters = string.ascii_uppercase + string.digits
        return ''.join(secrets.choice(characters) for _ in range(length))
    
    def get_active_subscription(self) -> Optional['Subscription']:
        """Get the user's active subscription."""
        for subscription in self.subscriptions:
            if subscription.is_active():
                return subscription
        return None
    
    def get_referral_earnings(self) -> float:
        """Calculate total referral earnings."""
        total = 0.0
        for referral in self.referrals_made:
            total += float(referral.commission_amount_usd or 0)
        return total
    
    def get_unpaid_referral_earnings(self) -> float:
        """Calculate unpaid referral earnings."""
        total = 0.0
        for referral in self.referrals_made:
            if not referral.commission_paid:
                total += float(referral.commission_amount_usd or 0)
        return total
    
    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username={self.username})>"


class SubscriptionPlan(Base):
    """Subscription plan model."""
    
    __tablename__ = "subscription_plans"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    duration_days = Column(Integer, nullable=False)
    price_usd = Column(DECIMAL(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="plan")
    
    def __repr__(self):
        return f"<SubscriptionPlan(id={self.id}, name={self.name}, price=${self.price_usd})>"


class Subscription(Base):
    """User subscription model."""
    
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    status = Column(String(20), default=SubscriptionStatus.ACTIVE.value, index=True)
    is_trial = Column(Boolean, default=False)
    trial_days_remaining = Column(Integer, default=0)
    auto_renew = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")
    
    def is_active(self) -> bool:
        """Check if subscription is currently active."""
        now = datetime.utcnow()
        return (
            self.status == SubscriptionStatus.ACTIVE.value and
            self.start_date <= now <= self.end_date
        )
    
    def is_expired(self) -> bool:
        """Check if subscription is expired."""
        return datetime.utcnow() > self.end_date
    
    def days_until_expiry(self) -> int:
        """Get number of days until subscription expires."""
        if self.is_expired():
            return 0
        return (self.end_date - datetime.utcnow()).days
    
    def extend_subscription(self, days: int) -> None:
        """Extend subscription by specified number of days."""
        self.end_date += timedelta(days=days)
        self.updated_at = datetime.utcnow()
    
    def __repr__(self):
        return f"<Subscription(id={self.id}, user_id={self.user_id}, status={self.status})>"


class Payment(Base):
    """Payment model for tracking all payment transactions."""
    
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    payment_method = Column(String(50), nullable=False)
    amount_usd = Column(DECIMAL(10, 2), nullable=False)
    amount_crypto = Column(DECIMAL(20, 8), nullable=True)
    crypto_currency = Column(String(10), nullable=True)
    transaction_hash = Column(String(255), unique=True, nullable=True, index=True)
    telegram_payment_charge_id = Column(String(255), unique=True, nullable=True)
    ton_transaction_id = Column(String(255), unique=True, nullable=True)
    payment_provider_id = Column(String(255), nullable=True)
    status = Column(String(20), default=PaymentStatus.PENDING.value, index=True)
    payment_data = Column(JSON, nullable=True)  # Store additional provider data
    created_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="payments")
    subscription = relationship("Subscription", back_populates="payments")
    
    def mark_completed(self) -> None:
        """Mark payment as completed."""
        self.status = PaymentStatus.COMPLETED.value
        self.completed_at = datetime.utcnow()
    
    def mark_failed(self) -> None:
        """Mark payment as failed."""
        self.status = PaymentStatus.FAILED.value
    
    def __repr__(self):
        return f"<Payment(id={self.id}, user_id={self.user_id}, method={self.payment_method}, amount=${self.amount_usd})>"


class Referral(Base):
    """Referral tracking model."""
    
    __tablename__ = "referrals"
    
    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    referred_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    commission_amount_usd = Column(DECIMAL(10, 2), default=0.00)
    commission_paid = Column(Boolean, default=False)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    paid_at = Column(DateTime, nullable=True)
    
    # Relationships
    referrer = relationship("User", foreign_keys=[referrer_id], back_populates="referrals_made")
    referred_user = relationship("User", foreign_keys=[referred_user_id], back_populates="referrals_received")
    payment = relationship("Payment")
    
    # Unique constraint
    __table_args__ = (UniqueConstraint('referrer_id', 'referred_user_id', name='unique_referral'),)
    
    def mark_paid(self) -> None:
        """Mark commission as paid."""
        self.commission_paid = True
        self.paid_at = datetime.utcnow()
    
    def __repr__(self):
        return f"<Referral(id={self.id}, referrer_id={self.referrer_id}, commission=${self.commission_amount_usd})>"


class ReferralPayout(Base):
    """Referral payout requests model."""
    
    __tablename__ = "referral_payouts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount_usd = Column(DECIMAL(10, 2), nullable=False)
    payout_method = Column(String(50), nullable=True)  # 'ton', 'usdt', 'manual'
    payout_address = Column(String(255), nullable=True)
    status = Column(String(20), default=PayoutStatus.REQUESTED.value)
    admin_notes = Column(Text, nullable=True)
    requested_at = Column(DateTime, default=func.now())
    processed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="referral_payouts")
    
    def mark_processing(self) -> None:
        """Mark payout as processing."""
        self.status = PayoutStatus.PROCESSING.value
        self.processed_at = datetime.utcnow()
    
    def mark_completed(self, admin_notes: str = None) -> None:
        """Mark payout as completed."""
        self.status = PayoutStatus.COMPLETED.value
        self.completed_at = datetime.utcnow()
        if admin_notes:
            self.admin_notes = admin_notes
    
    def __repr__(self):
        return f"<ReferralPayout(id={self.id}, user_id={self.user_id}, amount=${self.amount_usd})>"


class ProxyCredential(Base, EncryptionMixin):
    """Encrypted proxy credentials model."""
    
    __tablename__ = "proxy_credentials"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    region = Column(String(10), nullable=False)
    proxy_host = Column(String(255), nullable=False)
    proxy_port = Column(Integer, nullable=False)
    proxy_username_encrypted = Column(Text, nullable=False)  # Fernet encrypted
    proxy_password_encrypted = Column(Text, nullable=False)  # Fernet encrypted
    is_active = Column(Boolean, default=True)
    assigned_at = Column(DateTime, default=func.now())
    revoked_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="proxy_credentials")
    
    # Unique constraint
    __table_args__ = (UniqueConstraint('user_id', 'region', name='unique_user_region'),)
    
    def set_credentials(self, username: str, password: str, encryption_key: str) -> None:
        """Set encrypted proxy credentials."""
        self.proxy_username_encrypted = self.encrypt_data(username, encryption_key)
        self.proxy_password_encrypted = self.encrypt_data(password, encryption_key)
    
    def get_credentials(self, encryption_key: str) -> tuple[str, str]:
        """Get decrypted proxy credentials."""
        username = self.decrypt_data(self.proxy_username_encrypted, encryption_key)
        password = self.decrypt_data(self.proxy_password_encrypted, encryption_key)
        return username, password
    
    def revoke(self) -> None:
        """Revoke proxy credentials."""
        self.is_active = False
        self.revoked_at = datetime.utcnow()
    
    def __repr__(self):
        return f"<ProxyCredential(id={self.id}, user_id={self.user_id}, region={self.region})>"


class BotMessage(Base):
    """Bot messages/instructions model."""
    
    __tablename__ = "bot_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    message_key = Column(String(100), unique=True, nullable=False)
    message_text = Column(Text, nullable=False)
    language_code = Column(String(10), default="en")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<BotMessage(id={self.id}, key={self.message_key}, lang={self.language_code})>"


class AdminAuditLog(Base):
    """Admin audit log model."""
    
    __tablename__ = "admin_audit_log"
    
    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)  # Support IPv6
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    admin_user = relationship("User", foreign_keys=[admin_user_id])
    target_user = relationship("User", foreign_keys=[target_user_id])
    
    def __repr__(self):
        return f"<AdminAuditLog(id={self.id}, action={self.action}, admin_id={self.admin_user_id})>"


class ObserverLog(Base):
    """Observer service logs model."""
    
    __tablename__ = "observer_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(50), nullable=False)  # 'expiry_check', 'reminder', 'revocation'
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    status = Column(String(20), nullable=False)  # 'success', 'failed', 'skipped'
    message = Column(Text, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=func.now(), index=True)
    
    # Relationships
    user = relationship("User")
    subscription = relationship("Subscription")
    
    def __repr__(self):
        return f"<ObserverLog(id={self.id}, task={self.task_type}, status={self.status})>"


# Database utility functions
class DatabaseManager:
    """Database manager for common operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create_user(self, telegram_id: int, username: str = None, 
                   first_name: str = None, last_name: str = None,
                   referred_by_code: str = None) -> User:
        """Create a new user."""
        # Check if user already exists
        existing_user = self.session.query(User).filter(User.telegram_id == telegram_id).first()
        if existing_user:
            return existing_user
        
        # Handle referral
        referred_by_user_id = None
        if referred_by_code:
            referrer = self.session.query(User).filter(User.referral_code == referred_by_code).first()
            if referrer:
                referred_by_user_id = referrer.id
        
        # Create new user
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            referred_by_user_id=referred_by_user_id
        )
        
        self.session.add(user)
        self.session.commit()
        
        # Create referral record if applicable
        if referred_by_user_id:
            referral = Referral(
                referrer_id=referred_by_user_id,
                referred_user_id=user.id
            )
            self.session.add(referral)
            self.session.commit()
        
        return user
    
    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID."""
        return self.session.query(User).filter(User.telegram_id == telegram_id).first()
    
    def create_subscription(self, user_id: int, plan_id: int, 
                          is_trial: bool = False, trial_days: int = 0) -> Subscription:
        """Create a new subscription."""
        plan = self.session.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
        if not plan:
            raise ValueError(f"Subscription plan {plan_id} not found")
        
        start_date = datetime.utcnow()
        if is_trial:
            end_date = start_date + timedelta(days=trial_days)
            status = SubscriptionStatus.TRIAL.value
        else:
            end_date = start_date + timedelta(days=plan.duration_days)
            status = SubscriptionStatus.ACTIVE.value
        
        subscription = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
            is_trial=is_trial,
            trial_days_remaining=trial_days if is_trial else 0
        )
        
        self.session.add(subscription)
        self.session.commit()
        
        return subscription
    
    def get_expiring_subscriptions(self, days_before: int) -> List[Subscription]:
        """Get subscriptions expiring in specified days."""
        target_date = datetime.utcnow() + timedelta(days=days_before)
        return self.session.query(Subscription).filter(
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.end_date <= target_date,
            Subscription.end_date > datetime.utcnow()
        ).all()
    
    def get_expired_subscriptions(self) -> List[Subscription]:
        """Get all expired subscriptions."""
        return self.session.query(Subscription).filter(
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.end_date <= datetime.utcnow()
        ).all()
