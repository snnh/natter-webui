from flask import Flask, render_template, request, jsonify
import subprocess
import threading
import os
import signal
import logging
import shlex
from datetime import datetime

app = Flask(__name__,
            template_folder='web',
            static_folder='web',
            static_url_path='')
app.config['SECRET_KEY'] = os.urandom(24)
logging.basicConfig(level=logging.INFO)

# 进程管理
natter_process = None
process_lock = threading.Lock()
log_buffer = []
log_lock = threading.Lock()

def run_natter(params):
    global natter_process, log_buffer
    try:
        # 构造命令时直接传递所有参数
        cmd = ["python3", "natter.py"] + params
        logging.info(f"执行命令: {' '.join(cmd)}")
        
        natter_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            preexec_fn=os.setsid
        )

        with log_lock:
            log_buffer.clear()

        while True:
            line = natter_process.stdout.readline()
            if not line and natter_process.poll() is not None:
                break
            if line:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_entry = f"[{timestamp}] {line.strip()}"
                with log_lock:
                    log_buffer.append(log_entry)
                    if len(log_buffer) > 100:
                        log_buffer.pop(0)

    except Exception as e:
        logging.error(f"运行Natter时出错: {str(e)}")
    finally:
        with process_lock:
            natter_process = None

@app.route('/')
def index():
    return render_template('index.html')

def validate_parameters(data):
    errors = []
    
    # 端口验证
    port_fields = ['bind_port', 'target_port']
    for field in port_fields:
        if data.get(field):
            try:
                port = int(data[field])
                if not (0 <= port <= 65535):
                    errors.append(f"{field} 端口无效")
            except ValueError:
                errors.append(f"{field} 必须为整数")
    
    # UDP模式特殊验证
    if data.get('udp_mode'):
        # 检查转发方法兼容性
        if data.get('forward_method') in ['iptables', 'nftables']:
            errors.append(f"UDP模式不支持 {data['forward_method']} 转发方法")
        
    
    # 保活间隔验证
    if data.get('keepalive_interval'):
        if not data['keepalive_interval'].isdigit():
            errors.append("保活间隔必须为整数")
        elif int(data['keepalive_interval']) < 1:
            errors.append("保活间隔必须大于0")
    
    # 文件路径验证
    if data.get('notify_script'):
        script_path = data['notify_script']
        if not os.path.exists(script_path):
            errors.append("通知脚本路径不存在")
        elif not os.access(script_path, os.X_OK):
            errors.append("通知脚本没有执行权限")
    
    if errors:
        raise ValueError(" | ".join(errors))

@app.route('/start', methods=['POST'])
def start_service():
    data = request.json
    logging.debug(f"接收到的参数: {data}")
    global natter_process
    with process_lock:
        if natter_process is not None:
            return jsonify({"status": "error", "message": "服务已在运行"})

        data = request.json
        params = []
        param_config = [
            # (参数名, 命令行选项, 需要值)
            ('verbose', '-v', False),
            ('quit_on_change', '-q', False),
            ('udp_mode', '-u', False),  # UDP模式参数
            ('upnp_enable', '-U', False),
            ('keepalive_interval', '-k', True),
            ('stun_server', '-s', True),
            ('heartbeat_server', '-h', True),
            ('notify_script', '-e', True),
            ('bind_interface', '-i', True),
            ('bind_port', '-b', True),
            ('forward_method', '-m', True),
            ('target_ip', '-t', True),
            ('target_port', '-p', True),
            ('retry_mode', '-r', False)
        ]

        try:
            validate_parameters(data)
            
            # 构建参数列表
            for param_name, flag, needs_value in param_config:
                value = data.get(param_name)
                if value:
                    if needs_value:
                        if isinstance(value, bool):
                            if value:
                                params.append(flag)
                        else:
                            params.extend([flag, str(value)])
                    else:
                        if value:  # 处理开关型参数
                            params.append(flag)
            
            # 特殊处理UDP模式
            if data.get('udp_mode'):
                # 添加UDP专用参数
                params.append('-u')
                # 检查是否需要添加默认心跳服务器
                if not data.get('heartbeat_server'):
                    params.extend(['-h', '8.8.8.8:53'])  # UDP默认使用DNS服务器

            logging.debug(f"最终参数列表: {params}")
            
            thread = threading.Thread(target=run_natter, args=(params,))
            thread.start()
            return jsonify({"status": "success", "message": "服务启动成功"})
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)})
        except Exception as e:
            logging.error(f"启动失败: {str(e)}", exc_info=True)
            return jsonify({"status": "error", "message": "内部服务器错误"})

@app.route('/stop', methods=['POST'])
def stop_service():
    global natter_process
    with process_lock:
        if natter_process:
            try:
                # 关键修改点：直接使用进程 PID 作为进程组 ID
                os.killpg(natter_process.pid, signal.SIGTERM)
                logging.info(f"已向进程组 {natter_process.pid} 发送 SIGTERM 信号")
                natter_process = None
                return jsonify({"status": "success", "message": "服务已停止"})
            except ProcessLookupError:
                # 添加日志记录
                logging.warning("尝试终止不存在的进程")
                return jsonify({"status": "error", "message": "进程不存在"})
            except Exception as e:
                logging.error(f"停止失败: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": "停止服务失败"})
        return jsonify({"status": "error", "message": "没有正在运行的服务"})

@app.route('/status')
def get_status():
    with process_lock, log_lock:
        return jsonify({
            "running": natter_process is not None,
            "logs": log_buffer[-20:]  # 返回最近20条日志
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)