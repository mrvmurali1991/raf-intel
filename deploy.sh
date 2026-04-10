#!/bin/bash
set -e

echo "=== RAF Intelligence Deployment ==="

# 1. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker $USER
    echo "Docker installed. You may need to log out and back in for group permissions."
fi

# 2. Install MySQL if not present
if ! command -v mysql &> /dev/null; then
    echo "Installing MySQL 8..."
    sudo apt-get update
    sudo apt-get install -y mysql-server
    sudo systemctl enable mysql
    sudo systemctl start mysql
    echo "Setting MySQL root password..."
    sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'root'; FLUSH PRIVILEGES;"
fi

# 3. Create database
echo "Creating raf_intelligence database..."
mysql -h 127.0.0.1 -u root -proot < ~/raf-intelligence/database/schema.sql || \
mysql -u root -proot < ~/raf-intelligence/database/schema.sql

# 4. Setup Python backend
echo "Setting up backend..."
sudo apt-get install -y python3-pip python3-venv nodejs npm
cd ~/raf-intelligence/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Setup frontend
echo "Setting up frontend..."
cd ~/raf-intelligence/frontend
npm install
npm run build

# 6. Create systemd services
echo "Creating systemd services..."

sudo tee /etc/systemd/system/raf-backend.service > /dev/null <<EOF
[Unit]
Description=RAF Intelligence Backend
After=mysql.service
Wants=mysql.service

[Service]
User=$USER
WorkingDirectory=/home/$USER/raf-intelligence/backend
Environment=PATH=/home/$USER/raf-intelligence/backend/venv/bin:/usr/bin
EnvironmentFile=/home/$USER/raf-intelligence/.env
ExecStart=/home/$USER/raf-intelligence/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8500
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/raf-frontend.service > /dev/null <<EOF
[Unit]
Description=RAF Intelligence Frontend
After=raf-backend.service

[Service]
User=$USER
WorkingDirectory=/home/$USER/raf-intelligence/frontend
Environment=NODE_ENV=production
Environment=NEXT_PUBLIC_API_URL=http://$(hostname -I | awk '{print $1}'):8500
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable raf-backend raf-frontend
sudo systemctl start raf-backend
sudo systemctl start raf-frontend

echo ""
echo "=== Deployment Complete ==="
echo "Backend:  http://$(hostname -I | awk '{print $1}'):8500"
echo "Frontend: http://$(hostname -I | awk '{print $1}'):3000"
echo "API Docs: http://$(hostname -I | awk '{print $1}'):8500/docs"
