#!/bin/bash
# CryptoTrader EC2 Setup Script
# Run this on a fresh Ubuntu 22.04+ EC2 instance
# Usage: bash setup.sh

set -euo pipefail

APP_DIR="/home/ubuntu/CryptoTrader"
VENV_DIR="$APP_DIR/venv"

echo "=== CryptoTrader EC2 Setup ==="

# 1. System packages
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3.11 python3.11-venv python3-pip git

# 2. Ensure NTP is running (fixes clock drift)
echo "[2/6] Configuring NTP..."
sudo timedatectl set-ntp true
echo "  Time sync: $(timedatectl show --property=NTPSynchronized --value)"

# 3. Set up project directory
echo "[3/6] Setting up project..."
if [ ! -d "$APP_DIR" ]; then
    echo "  ERROR: Project not found at $APP_DIR"
    echo "  First, copy project files from your Windows machine:"
    echo "    scp -r /path/to/CryptoTrader ubuntu@<ec2-ip>:/home/ubuntu/"
    exit 1
fi

# 4. Create virtual environment and install deps
echo "[4/6] Setting up Python environment..."
python3.11 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$APP_DIR/requirements.txt" -q

# 5. Ensure data directory exists
echo "[5/6] Setting up data directory..."
mkdir -p "$APP_DIR/data/historical"

# Check for .env
if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "  WARNING: No .env file found. Create one with:"
    echo "    nano $APP_DIR/.env"
    echo ""
    echo "  Required contents:"
    echo "    BINANCE_API_KEY=your_key_here"
    echo "    BINANCE_API_SECRET=your_secret_here"
    echo "    CRYPTOPANIC_API_KEY=your_key_here"
    echo ""
fi

# 6. Install systemd service
echo "[6/6] Installing systemd service..."
sudo cp "$APP_DIR/deploy/cryptotrader.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cryptotrader

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Create .env file:  nano $APP_DIR/.env"
echo "  2. Whitelist EC2 IP on Binance API settings"
echo "  3. Start the bot:     sudo systemctl start cryptotrader"
echo "  4. Check status:      sudo systemctl status cryptotrader"
echo "  5. View logs:         journalctl -u cryptotrader -f"
echo "  6. Dashboard:         ssh -L 5000:127.0.0.1:5000 ubuntu@<ec2-ip>"
echo "                        then open http://127.0.0.1:5000"
