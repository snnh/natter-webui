#!/bin/bash
# 文件名：uninstall-service.sh

sudo systemctl stop natter-web
sudo systemctl disable natter-web
sudo rm -f /etc/systemd/system/natter-web.service
sudo systemctl daemon-reload
echo "服务卸载成功"