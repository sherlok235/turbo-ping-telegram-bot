#!/bin/bash

# Turbo Ping Bot Deployment Script
# This script helps deploy and manage the Turbo Ping Telegram Bot system

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    
    print_success "Docker and Docker Compose are installed"
}

# Check configuration
check_config() {
    print_status "Checking configuration..."
    
    if [ ! -f "config/config.md" ]; then
        print_error "Configuration file config/config.md not found!"
        exit 1
    fi
    
    # Check for required configuration values
    if ! grep -q "BOT_TOKEN=" config/config.md; then
        print_warning "BOT_TOKEN not found in configuration"
    fi
    
    if ! grep -q "ENCRYPTION_KEY=" config/config.md; then
        print_warning "ENCRYPTION_KEY not found in configuration"
    fi
    
    print_success "Configuration file found"
}

# Generate encryption key if not exists
generate_encryption_key() {
    if ! grep -q "ENCRYPTION_KEY=" config/config.md || grep -q "ENCRYPTION_KEY=your-fernet-encryption-key" config/config.md; then
        print_status "Generating new encryption key..."
        
        # Generate Fernet key using Python
        ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || echo "")
        
        if [ -n "$ENCRYPTION_KEY" ]; then
            # Replace the placeholder in config file
            sed -i.bak "s/ENCRYPTION_KEY=your-fernet-encryption-key-here-32-bytes-base64-encoded/ENCRYPTION_KEY=$ENCRYPTION_KEY/" config/config.md
            print_success "Encryption key generated and updated in config"
        else
            print_warning "Could not generate encryption key automatically. Please set it manually."
        fi
    fi
}

# Create necessary directories
create_directories() {
    print_status "Creating necessary directories..."
    
    mkdir -p logs
    mkdir -p data/postgres
    mkdir -p data/redis
    
    # Set permissions
    chmod 755 logs
    
    print_success "Directories created"
}

# Build Docker images
build_images() {
    print_status "Building Docker images..."
    
    docker-compose build --no-cache
    
    print_success "Docker images built successfully"
}

# Start services
start_services() {
    print_status "Starting services..."
    
    # Start database first
    docker-compose up -d db redis
    
    # Wait for database to be ready
    print_status "Waiting for database to be ready..."
    sleep 10
    
    # Start other services
    docker-compose up -d
    
    print_success "All services started"
}

# Stop services
stop_services() {
    print_status "Stopping services..."
    
    docker-compose down
    
    print_success "Services stopped"
}

# Show service status
show_status() {
    print_status "Service status:"
    docker-compose ps
    
    echo ""
    print_status "Service logs (last 20 lines):"
    docker-compose logs --tail=20
}

# Run tests
run_tests() {
    print_status "Running system tests..."
    
    # Wait for services to be ready
    sleep 5
    
    # Run tests
    python3 tests/test_system.py
    
    if [ $? -eq 0 ]; then
        print_success "All tests passed!"
    else
        print_error "Some tests failed. Check the output above."
        exit 1
    fi
}

# Show logs
show_logs() {
    local service=${1:-""}
    
    if [ -n "$service" ]; then
        print_status "Showing logs for $service:"
        docker-compose logs -f "$service"
    else
        print_status "Showing logs for all services:"
        docker-compose logs -f
    fi
}

# Backup database
backup_database() {
    print_status "Creating database backup..."
    
    local backup_file="backup_$(date +%Y%m%d_%H%M%S).sql"
    
    docker-compose exec -T db pg_dump -U turbo_ping_user turbo_ping_db > "$backup_file"
    
    if [ $? -eq 0 ]; then
        print_success "Database backup created: $backup_file"
    else
        print_error "Database backup failed"
        exit 1
    fi
}

# Restore database
restore_database() {
    local backup_file="$1"
    
    if [ -z "$backup_file" ]; then
        print_error "Please specify backup file: ./deploy.sh restore <backup_file>"
        exit 1
    fi
    
    if [ ! -f "$backup_file" ]; then
        print_error "Backup file not found: $backup_file"
        exit 1
    fi
    
    print_status "Restoring database from $backup_file..."
    
    # Stop services except database
    docker-compose stop bot admin observer
    
    # Restore database
    docker-compose exec -T db psql -U turbo_ping_user -d turbo_ping_db < "$backup_file"
    
    if [ $? -eq 0 ]; then
        print_success "Database restored successfully"
        # Restart services
        docker-compose up -d
    else
        print_error "Database restore failed"
        exit 1
    fi
}

# Update system
update_system() {
    print_status "Updating system..."
    
    # Pull latest changes (if using git)
    if [ -d ".git" ]; then
        git pull
    fi
    
    # Rebuild images
    build_images
    
    # Restart services
    docker-compose down
    start_services
    
    print_success "System updated successfully"
}

# Show help
show_help() {
    echo "Turbo Ping Bot Deployment Script"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  deploy     - Full deployment (build, start, test)"
    echo "  start      - Start all services"
    echo "  stop       - Stop all services"
    echo "  restart    - Restart all services"
    echo "  status     - Show service status"
    echo "  logs [service] - Show logs (optionally for specific service)"
    echo "  test       - Run system tests"
    echo "  backup     - Create database backup"
    echo "  restore <file> - Restore database from backup"
    echo "  update     - Update and restart system"
    echo "  build      - Build Docker images"
    echo "  help       - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 deploy          # Full deployment"
    echo "  $0 logs bot        # Show bot logs"
    echo "  $0 backup          # Create backup"
    echo "  $0 restore backup.sql # Restore from backup"
}

# Main script logic
main() {
    local command=${1:-"help"}
    
    case $command in
        "deploy")
            print_status "Starting full deployment..."
            check_docker
            check_config
            generate_encryption_key
            create_directories
            build_images
            start_services
            run_tests
            print_success "Deployment completed successfully!"
            echo ""
            print_status "Access points:"
            echo "  - Admin Panel: http://localhost:8000"
            echo "  - Bot: Start chatting with your bot on Telegram"
            echo "  - Database: localhost:5432"
            ;;
        "start")
            check_docker
            start_services
            ;;
        "stop")
            stop_services
            ;;
        "restart")
            stop_services
            start_services
            ;;
        "status")
            show_status
            ;;
        "logs")
            show_logs "$2"
            ;;
        "test")
            run_tests
            ;;
        "backup")
            backup_database
            ;;
        "restore")
            restore_database "$2"
            ;;
        "update")
            update_system
            ;;
        "build")
            build_images
            ;;
        "help"|*)
            show_help
            ;;
    esac
}

# Run main function with all arguments
main "$@"
