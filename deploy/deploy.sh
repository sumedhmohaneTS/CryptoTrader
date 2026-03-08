#!/bin/bash
# Deploy CryptoTrader to EC2 from local machine
# Usage: bash deploy/deploy.sh <ec2-ip> [ssh-key-path]
#
# Example:
#   bash deploy/deploy.sh 54.123.45.67
#   bash deploy/deploy.sh 54.123.45.67 ~/.ssh/my-key.pem

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: bash deploy/deploy.sh <ec2-ip> [ssh-key-path]"
    exit 1
fi

EC2_IP="$1"
SSH_KEY="${2:-}"
EC2_USER="ubuntu"
REMOTE_DIR="/home/$EC2_USER/CryptoTrader"

# Build SSH/SCP options
SSH_OPTS="-o StrictHostKeyChecking=no"
if [ -n "$SSH_KEY" ]; then
    SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
fi

echo "=== Deploying CryptoTrader to $EC2_IP ==="

# Get project root (parent of deploy/)
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# 1. Sync project files (exclude heavy/sensitive stuff)
echo "[1/3] Syncing project files..."
rsync -avz --progress \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude 'venv' \
    --exclude '*.log' \
    --exclude '.env' \
    --exclude 'data/trading.db' \
    --exclude '*.pyc' \
    --exclude '.claude' \
    -e "ssh $SSH_OPTS" \
    "$PROJECT_DIR/" \
    "$EC2_USER@$EC2_IP:$REMOTE_DIR/"

# 2. Sync database (trades.db) separately — important for state
echo "[2/3] Syncing database..."
if [ -f "$PROJECT_DIR/data/trades.db" ]; then
    rsync -avz --progress \
        -e "ssh $SSH_OPTS" \
        "$PROJECT_DIR/data/trades.db" \
        "$EC2_USER@$EC2_IP:$REMOTE_DIR/data/trades.db"
fi

# 3. Run setup on EC2
echo "[3/3] Running setup on EC2..."
ssh $SSH_OPTS "$EC2_USER@$EC2_IP" "bash $REMOTE_DIR/deploy/setup.sh"

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Don't forget to:"
echo "  1. Create .env on EC2:  ssh $SSH_OPTS $EC2_USER@$EC2_IP 'nano $REMOTE_DIR/.env'"
echo "  2. Whitelist EC2's Elastic IP on Binance"
echo "  3. Start:  ssh $SSH_OPTS $EC2_USER@$EC2_IP 'sudo systemctl start cryptotrader'"
