#!/bin/bash
# 文件名：install-service.sh

# 获取当前绝对路径
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 创建服务文件内容
SERVICE_CONTENT="[Unit]
Description=Natter Web Control Service
After=network.target

[Service]
User=$(whoami)
Group=$(id -gn)
WorkingDirectory=${PROJECT_DIR}
ExecStart=$(which gunicorn) --bind 127.0.0.1:5000 --workers 2 natter_web:app
Restart=always
RestartSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target"

# 写入服务文件
echo "$SERVICE_CONTENT" | sudo tee /etc/systemd/system/natter-web.service > /dev/null

# 重新加载systemd
sudo systemctl daemon-reload
echo "服务安装成功！"
echo "使用方法："
echo "  启动服务：sudo systemctl start natter-web"
echo "  开机启动：sudo systemctl enable natter-web"