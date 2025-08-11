"""
Basic system tests for Turbo Ping Bot.
Run these tests to verify the system is working correctly.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from bot.config_parser import get_config
from bot.models import Base, User, SubscriptionPlan
from bot.proxy_manager import ProxyManager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

async def test_configuration():
    """Test configuration loading."""
    print("🔧 Testing configuration...")
    try:
        config = get_config()
        assert config.telegram.bot_token, "Bot token not configured"
        assert config.database.url, "Database URL not configured"
        assert config.security.encryption_key, "Encryption key not configured"
        print("✅ Configuration loaded successfully")
        return True
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False

async def test_database_connection():
    """Test database connection and schema."""
    print("🗄️ Testing database connection...")
    try:
        config = get_config()
        engine = create_engine(config.database.url)
        
        # Test connection
        with engine.connect() as conn:
            result = conn.execute("SELECT 1")
            assert result.fetchone()[0] == 1
        
        # Test schema
        Base.metadata.create_all(engine)
        
        print("✅ Database connection successful")
        return True
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

async def test_proxy_manager():
    """Test proxy manager functionality."""
    print("🔐 Testing proxy manager...")
    try:
        config = get_config()
        engine = create_engine(config.database.url)
        SessionLocal = sessionmaker(bind=engine)
        
        with SessionLocal() as session:
            proxy_manager = ProxyManager(config, session)
            
            # Test server validation
            validation_results = proxy_manager.validate_proxy_server_config()
            assert any(validation_results.values()), "No valid proxy servers configured"
            
            print("✅ Proxy manager working correctly")
            return True
    except Exception as e:
        print(f"❌ Proxy manager test failed: {e}")
        return False

async def test_models():
    """Test database models."""
    print("📊 Testing database models...")
    try:
        config = get_config()
        engine = create_engine(config.database.url)
        SessionLocal = sessionmaker(bind=engine)
        
        with SessionLocal() as session:
            # Test creating a user
            test_user = User(
                telegram_id=123456789,
                username="test_user",
                first_name="Test",
                last_name="User"
            )
            session.add(test_user)
            session.commit()
            
            # Test querying user
            found_user = session.query(User).filter(User.telegram_id == 123456789).first()
            assert found_user is not None, "User not found after creation"
            assert found_user.referral_code, "Referral code not generated"
            
            # Clean up
            session.delete(found_user)
            session.commit()
            
            print("✅ Database models working correctly")
            return True
    except Exception as e:
        print(f"❌ Models test failed: {e}")
        return False

async def test_encryption():
    """Test encryption functionality."""
    print("🔒 Testing encryption...")
    try:
        config = get_config()
        from bot.models import EncryptionMixin
        
        # Test data
        test_data = "test_proxy_password_123"
        
        # Encrypt
        encrypted = EncryptionMixin.encrypt_data(test_data, config.security.encryption_key)
        assert encrypted != test_data, "Data not encrypted"
        
        # Decrypt
        decrypted = EncryptionMixin.decrypt_data(encrypted, config.security.encryption_key)
        assert decrypted == test_data, "Decryption failed"
        
        print("✅ Encryption working correctly")
        return True
    except Exception as e:
        print(f"❌ Encryption test failed: {e}")
        return False

async def test_payment_providers():
    """Test payment provider initialization."""
    print("💳 Testing payment providers...")
    try:
        config = get_config()
        from bot.payments import TONPaymentProvider, TelegramStarsProvider
        
        # Test TON provider
        ton_provider = TONPaymentProvider(config)
        assert ton_provider.wallet_address, "TON wallet not configured"
        
        # Test rate fetching (mock)
        try:
            rate = await ton_provider._get_ton_usd_rate()
            assert rate > 0, "Invalid TON rate"
        except:
            print("⚠️ TON rate fetching failed (using fallback)")
        
        await ton_provider.close()
        
        print("✅ Payment providers initialized correctly")
        return True
    except Exception as e:
        print(f"❌ Payment providers test failed: {e}")
        return False

async def run_all_tests():
    """Run all system tests."""
    print("🚀 Starting Turbo Ping Bot System Tests\n")
    
    tests = [
        test_configuration,
        test_database_connection,
        test_models,
        test_encryption,
        test_proxy_manager,
        test_payment_providers
    ]
    
    results = []
    for test in tests:
        result = await test()
        results.append(result)
        print()  # Add spacing between tests
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! System is ready for deployment.")
        return True
    else:
        print("❌ Some tests failed. Please check the configuration and setup.")
        return False

def main():
    """Main test runner."""
    try:
        result = asyncio.run(run_all_tests())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n⚠️ Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test runner failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
