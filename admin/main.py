"""
Admin Panel for Turbo Ping Bot.
FastAPI-based web interface for managing users, subscriptions, and referrals.
"""

import logging
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, Depends, HTTPException, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import JWTError, jwt
import bcrypt

# Add parent directory to path for imports
sys.path.append('/app')

from bot.config_parser import get_config, BotConfig
from bot.models import (
    User, Subscription, SubscriptionPlan, Payment, PaymentStatus,
    Referral, ReferralPayout, ProxyCredential, AdminAuditLog,
    ObserverLog, DatabaseManager
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/admin.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Turbo Ping Admin Panel",
    description="Admin interface for managing Turbo Ping Bot",
    version="1.0.0"
)

# Configuration
config = get_config()

# Database setup
engine = create_engine(config.database.url, echo=config.debug_mode)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Templates and static files
templates = Jinja2Templates(directory="admin/templates")
app.mount("/static", StaticFiles(directory="admin/static"), name="static")


# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Authentication functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash."""
    return pwd_context.hash(password)


def create_access_token(data: dict) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=config.admin.session_expire_hours)
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode, 
        config.admin.secret_key, 
        algorithm="HS256"
    )
    return encoded_jwt


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token."""
    try:
        payload = jwt.decode(
            credentials.credentials, 
            config.admin.secret_key, 
            algorithms=["HS256"]
        )
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
        return username
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )


def log_admin_action(db: Session, admin_username: str, action: str, 
                    target_user_id: int = None, details: Dict = None,
                    ip_address: str = None, user_agent: str = None):
    """Log admin action to audit log."""
    try:
        # Get admin user
        admin_user = db.query(User).filter(User.username == admin_username).first()
        
        audit_log = AdminAuditLog(
            admin_user_id=admin_user.id if admin_user else None,
            action=action,
            target_user_id=target_user_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.add(audit_log)
        db.commit()
        
        logger.info(f"Admin action logged: {action} by {admin_username}")
        
    except Exception as e:
        logger.error(f"Failed to log admin action: {e}")


# Routes
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "turbo_ping_admin", "timestamp": datetime.utcnow()}


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle login."""
    try:
        # Verify credentials
        if username == config.admin.username and verify_password(password, config.admin.password_hash):
            # Create access token
            access_token = create_access_token(data={"sub": username})
            
            # Redirect to dashboard
            response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
            response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
            
            return response
        else:
            return templates.TemplateResponse(
                "login.html", 
                {"request": request, "error": "Invalid credentials"}
            )
    
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return templates.TemplateResponse(
            "login.html", 
            {"request": request, "error": "Login failed"}
        )


@app.get("/logout")
async def logout():
    """Handle logout."""
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Admin dashboard."""
    try:
        # Get authentication from cookie
        token = request.cookies.get("access_token")
        if not token or not token.startswith("Bearer "):
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        
        # Verify token
        try:
            payload = jwt.decode(token[7:], config.admin.secret_key, algorithms=["HS256"])
            username = payload.get("sub")
            if not username:
                return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        except JWTError:
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        
        # Get dashboard statistics
        total_users = db.query(User).count()
        active_subscriptions = db.query(Subscription).filter(
            Subscription.status == "active"
        ).count()
        total_payments = db.query(Payment).filter(
            Payment.status == PaymentStatus.COMPLETED.value
        ).count()
        
        # Calculate total revenue
        completed_payments = db.query(Payment).filter(
            Payment.status == PaymentStatus.COMPLETED.value
        ).all()
        total_revenue = sum(float(payment.amount_usd) for payment in completed_payments)
        
        # Get recent users
        recent_users = db.query(User).order_by(desc(User.created_at)).limit(10).all()
        
        # Get recent payments
        recent_payments = db.query(Payment).order_by(desc(Payment.created_at)).limit(10).all()
        
        # Get referral statistics
        total_referrals = db.query(Referral).count()
        pending_payouts = db.query(ReferralPayout).filter(
            ReferralPayout.status == "requested"
        ).count()
        
        stats = {
            "total_users": total_users,
            "active_subscriptions": active_subscriptions,
            "total_payments": total_payments,
            "total_revenue": total_revenue,
            "total_referrals": total_referrals,
            "pending_payouts": pending_payouts,
            "recent_users": recent_users,
            "recent_payments": recent_payments
        }
        
        return templates.TemplateResponse(
            "dashboard.html", 
            {"request": request, "stats": stats, "username": username}
        )
        
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "error": "Failed to load dashboard"}
        )


@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, page: int = 1, search: str = "", db: Session = Depends(get_db)):
    """Users management page."""
    try:
        # Authentication check
        token = request.cookies.get("access_token")
        if not token or not token.startswith("Bearer "):
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        
        # Pagination
        per_page = 20
        offset = (page - 1) * per_page
        
        # Build query
        query = db.query(User)
        
        if search:
            query = query.filter(
                (User.username.ilike(f"%{search}%")) |
                (User.first_name.ilike(f"%{search}%")) |
                (User.telegram_id.like(f"%{search}%"))
            )
        
        total_users = query.count()
        users = query.order_by(desc(User.created_at)).offset(offset).limit(per_page).all()
        
        # Calculate pagination
        total_pages = (total_users + per_page - 1) // per_page
        
        return templates.TemplateResponse(
            "users.html", 
            {
                "request": request,
                "users": users,
                "current_page": page,
                "total_pages": total_pages,
                "search": search,
                "total_users": total_users
            }
        )
        
    except Exception as e:
        logger.error(f"Users page error: {e}")
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "error": "Failed to load users"}
        )


@app.get("/user/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: int, db: Session = Depends(get_db)):
    """User detail page."""
    try:
        # Authentication check
        token = request.cookies.get("access_token")
        if not token or not token.startswith("Bearer "):
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        
        # Get user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get user's subscriptions
        subscriptions = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).order_by(desc(Subscription.created_at)).all()
        
        # Get user's payments
        payments = db.query(Payment).filter(
            Payment.user_id == user_id
        ).order_by(desc(Payment.created_at)).all()
        
        # Get user's referrals
        referrals_made = db.query(Referral).filter(
            Referral.referrer_id == user_id
        ).all()
        
        # Get user's proxy credentials
        proxy_creds = db.query(ProxyCredential).filter(
            ProxyCredential.user_id == user_id
        ).all()
        
        return templates.TemplateResponse(
            "user_detail.html", 
            {
                "request": request,
                "user": user,
                "subscriptions": subscriptions,
                "payments": payments,
                "referrals_made": referrals_made,
                "proxy_creds": proxy_creds
            }
        )
        
    except Exception as e:
        logger.error(f"User detail error: {e}")
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "error": "Failed to load user details"}
        )


@app.post("/user/{user_id}/extend_subscription")
async def extend_subscription(request: Request, user_id: int, days: int = Form(...), db: Session = Depends(get_db)):
    """Extend user subscription."""
    try:
        # Authentication check
        token = request.cookies.get("access_token")
        if not token or not token.startswith("Bearer "):
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        
        # Get username from token
        payload = jwt.decode(token[7:], config.admin.secret_key, algorithms=["HS256"])
        username = payload.get("sub")
        
        # Get user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get active subscription
        active_sub = user.get_active_subscription()
        if active_sub:
            active_sub.extend_subscription(days)
            db.commit()
            
            # Log admin action
            log_admin_action(
                db, username, "extend_subscription", user_id,
                {"days": days, "new_end_date": active_sub.end_date.isoformat()},
                request.client.host, request.headers.get("user-agent")
            )
            
            return RedirectResponse(
                url=f"/user/{user_id}?success=Subscription extended by {days} days", 
                status_code=status.HTTP_302_FOUND
            )
        else:
            return RedirectResponse(
                url=f"/user/{user_id}?error=No active subscription found", 
                status_code=status.HTTP_302_FOUND
            )
        
    except Exception as e:
        logger.error(f"Extend subscription error: {e}")
        return RedirectResponse(
            url=f"/user/{user_id}?error=Failed to extend subscription", 
            status_code=status.HTTP_302_FOUND
        )


@app.post("/user/{user_id}/grant_trial")
async def grant_trial(request: Request, user_id: int, days: int = Form(...), db: Session = Depends(get_db)):
    """Grant trial period to user."""
    try:
        # Authentication check
        token = request.cookies.get("access_token")
        if not token or not token.startswith("Bearer "):
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        
        # Get username from token
        payload = jwt.decode(token[7:], config.admin.secret_key, algorithms=["HS256"])
        username = payload.get("sub")
        
        # Get user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if user already has active subscription
        active_sub = user.get_active_subscription()
        if active_sub:
            return RedirectResponse(
                url=f"/user/{user_id}?error=User already has active subscription", 
                status_code=status.HTTP_302_FOUND
            )
        
        # Create trial subscription
        db_manager = DatabaseManager(db)
        trial_plan = db.query(SubscriptionPlan).first()
        
        if trial_plan:
            subscription = db_manager.create_subscription(
                user_id=user.id,
                plan_id=trial_plan.id,
                is_trial=True,
                trial_days=days
            )
            
            # Log admin action
            log_admin_action(
                db, username, "grant_trial", user_id,
                {"days": days, "subscription_id": subscription.id},
                request.client.host, request.headers.get("user-agent")
            )
            
            return RedirectResponse(
                url=f"/user/{user_id}?success=Trial period of {days} days granted", 
                status_code=status.HTTP_302_FOUND
            )
        else:
            return RedirectResponse(
                url=f"/user/{user_id}?error=No subscription plan found", 
                status_code=status.HTTP_302_FOUND
            )
        
    except Exception as e:
        logger.error(f"Grant trial error: {e}")
        return RedirectResponse(
            url=f"/user/{user_id}?error=Failed to grant trial", 
            status_code=status.HTTP_302_FOUND
        )


@app.get("/referrals", response_class=HTMLResponse)
async def referrals_page(request: Request, db: Session = Depends(get_db)):
    """Referrals management page."""
    try:
        # Authentication check
        token = request.cookies.get("access_token")
        if not token or not token.startswith("Bearer "):
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        
        # Get referral statistics
        total_referrals = db.query(Referral).count()
        total_commission = db.query(Referral).with_entities(Referral.commission_amount_usd).all()
        total_commission_amount = sum(float(r[0] or 0) for r in total_commission)
        
        # Get pending payouts
        pending_payouts = db.query(ReferralPayout).filter(
            ReferralPayout.status == "requested"
        ).order_by(desc(ReferralPayout.requested_at)).all()
        
        # Get recent referrals
        recent_referrals = db.query(Referral).order_by(desc(Referral.created_at)).limit(20).all()
        
        return templates.TemplateResponse(
            "referrals.html", 
            {
                "request": request,
                "total_referrals": total_referrals,
                "total_commission_amount": total_commission_amount,
                "pending_payouts": pending_payouts,
                "recent_referrals": recent_referrals
            }
        )
        
    except Exception as e:
        logger.error(f"Referrals page error: {e}")
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "error": "Failed to load referrals"}
        )


@app.post("/payout/{payout_id}/complete")
async def complete_payout(request: Request, payout_id: int, notes: str = Form(""), db: Session = Depends(get_db)):
    """Mark payout as completed."""
    try:
        # Authentication check
        token = request.cookies.get("access_token")
        if not token or not token.startswith("Bearer "):
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        
        # Get username from token
        payload = jwt.decode(token[7:], config.admin.secret_key, algorithms=["HS256"])
        username = payload.get("sub")
        
        # Get payout
        payout = db.query(ReferralPayout).filter(ReferralPayout.id == payout_id).first()
        if not payout:
            raise HTTPException(status_code=404, detail="Payout not found")
        
        # Mark as completed
        payout.mark_completed(notes)
        db.commit()
        
        # Log admin action
        log_admin_action(
            db, username, "complete_payout", payout.user_id,
            {"payout_id": payout_id, "amount": float(payout.amount_usd), "notes": notes},
            request.client.host, request.headers.get("user-agent")
        )
        
        return RedirectResponse(
            url="/referrals?success=Payout marked as completed", 
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        logger.error(f"Complete payout error: {e}")
        return RedirectResponse(
            url="/referrals?error=Failed to complete payout", 
            status_code=status.HTTP_302_FOUND
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
