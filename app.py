import json
import math
import errno
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from movement import create_gpx, interpolate

HOST = '127.0.0.1'
PORT = 8765
COMMAND_TIMEOUT = 30
CLEAR_TIMEOUT = 90
ROOT = Path(__file__).resolve().parent
LOCK = threading.Lock()
ACTIVE_PROCESS = None
ROUTE = None
PINNED_POINT = None
PINNED_ERROR = ''
RETRY_AT = 0
PROMPT = b'Press ENTER to exit>'
COMMANDS = {
    'devices': ['usbmux', 'list'],
    'clear': ['developer', 'dvt', 'simulate-location', 'clear'],
}


def stop_active_process():
    global ACTIVE_PROCESS, ROUTE
    process = ACTIVE_PROCESS
    ACTIVE_PROCESS = None
    route = ROUTE
    ROUTE = None
    try:
        if process is None or process.poll() is not None:
            return
        try:
            process.stdin.write(b'\n')
            process.stdin.flush()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    finally:
        if route is not None:
            route['path'].unlink(missing_ok=True)


def launch_location_command(args):
    command = [sys.executable, '-m', 'pymobiledevice3', *args]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, bufsize=0)
    output = bytearray()
    ready = threading.Event()
    first_update = threading.Event()
    first_point_time = [None]

    def read_output():
        line = bytearray()
        location_logs = 0
        while True:
            chunk = process.stdout.read(1)
            if not chunk:
                ready.set()
                first_update.set()
                return
            output.extend(chunk)
            if len(output) > 10000:
                del output[:-7500]
            line.extend(chunk)
            if chunk == b'\n':
                if b'set location to' in line:
                    location_logs += 1
                    if first_point_time[0] is None:
                        first_point_time[0] = time.monotonic()
                    if location_logs >= 2:
                        first_update.set()
                line.clear()
            if output.endswith(PROMPT):
                ready.set()
                first_update.set()

    threading.Thread(target=read_output, daemon=True).start()
    return process, output, ready, first_update, first_point_time


def set_location(args, point=None):
    global ACTIVE_PROCESS, PINNED_POINT, PINNED_ERROR, RETRY_AT
    stop_active_process()
    process, output, ready, _, _ = launch_location_command(args)
    if not ready.wait(timeout=COMMAND_TIMEOUT):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        details = output.decode('utf-8', errors='replace').strip()
        return {'ok': False, 'message':
                f'設定定位在 {COMMAND_TIMEOUT} 秒內未收到完成訊號。請先關閉其他正在執行定位指令的終端機，確認裝置已解鎖並保持 USB 連線，再試一次。'
                + (f'\n\n指令輸出：\n{details[-5000:]}' if details else '\n\n指令沒有輸出。')}

    message = output.decode('utf-8', errors='replace').strip()
    if process.poll() is None and PROMPT in output:
        ACTIVE_PROCESS = process
        PINNED_POINT = point
        PINNED_ERROR = ''
        RETRY_AT = 0
        return {'ok': True, 'message': '定位已設定。請保留控制台視窗開啟；改位置或恢復真實定位時會自動結束前一個定位程序。'}
    process.wait(timeout=5)
    return {'ok': False, 'message': message[-7500:] or '定位程序已結束，無法持續維持模擬位置。'}


def start_movement(start, end):
    global ACTIVE_PROCESS, ROUTE, PINNED_POINT, PINNED_ERROR
    try:
        path, distance, duration = create_gpx(start, end)
    except ValueError as exc:
        return {'ok': False, 'message': str(exc)}
    stop_active_process()
    PINNED_POINT = None
    PINNED_ERROR = ''
    try:
        process, output, ready, first_update, first_point_time = launch_location_command(
            ['developer', 'dvt', 'simulate-location', 'play', str(path)])
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if not first_update.wait(timeout=COMMAND_TIMEOUT):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        details = output.decode('utf-8', errors='replace').strip()
        path.unlink(missing_ok=True)
        return {'ok': False, 'message':
                f'移動指令未在 {COMMAND_TIMEOUT} 秒內完成第一個位置更新。請確認 USB 連線、裝置解鎖與開發者模式。'
                + (f'\n\n指令輸出：\n{details[-5000:]}' if details else '')}
    if process.poll() is not None:
        message = output.decode('utf-8', errors='replace').strip()
        path.unlink(missing_ok=True)
        return {'ok': False, 'message': message[-7500:] or '移動指令無法啟動'}
    ACTIVE_PROCESS = process
    ROUTE = {'start': start, 'end': end, 'distance': distance, 'duration': duration,
             'started': first_point_time[0] or time.monotonic(), 'path': path, 'output': output}
    return {'ok': True, 'message': f'移動程序已啟動，直線距離 {distance / 1000:.2f} 公里，預計約 {duration / 60:.1f} 分鐘。'}


def movement_status():
    route = ROUTE
    process = ACTIVE_PROCESS
    if route is None or process is None:
        if PINNED_POINT is not None:
            phase = 'fixed' if process is not None and process.poll() is None else 'reconnecting'
            return {'phase': phase, 'lat': PINNED_POINT[0], 'lon': PINNED_POINT[1],
                    'message': PINNED_ERROR}
        if PINNED_ERROR:
            return {'phase': 'failed', 'message': PINNED_ERROR}
        return {'phase': 'idle'}
    elapsed = max(0, time.monotonic() - route['started'])
    fraction = min(1, elapsed / route['duration'])
    point = interpolate(route['start'], route['end'], fraction)
    output = route['output']
    if PROMPT in output or (process.poll() is not None and process.returncode == 0):
        phase = 'complete'
        fraction = 1
        point = route['end']
    elif process.poll() is not None:
        phase = 'failed'
    else:
        phase = 'moving'
    return {'phase': phase, 'progress': round(fraction * 100, 1),
            'lat': round(point[0], 6), 'lon': round(point[1], 6),
            'start': route['start'], 'end': route['end'],
            'distance_km': round(route['distance'] / 1000, 2),
            'remaining_seconds': max(0, round(route['duration'] - elapsed)),
            'message': output.decode('utf-8', errors='replace')[-3000:] if phase == 'failed' else ''}


def stop_movement():
    if ROUTE is None:
        return {'ok': False, 'message': '目前沒有正在播放的路線'}
    position = movement_status()
    stop_active_process()
    if position['phase'] == 'failed':
        return {'ok': False, 'message': '移動程序已中斷，無法確認最後位置。請重新設定單點定位。'}
    args = ['developer', 'dvt', 'simulate-location', 'set', '--',
            str(position['lat']), str(position['lon'])]
    response = set_location(args, (position['lat'], position['lon']))
    if response['ok']:
        response['message'] = f"已停止移動並停在 {position['lat']}, {position['lon']}。"
    return response


def maintain_location():
    """Repair an ended DVT session and pin a finished route at its final point."""
    global PINNED_POINT, PINNED_ERROR, RETRY_AT
    while True:
        time.sleep(2)
        if not LOCK.acquire(blocking=False):
            continue
        try:
            if ROUTE is not None and ACTIVE_PROCESS is not None and PROMPT in ROUTE['output']:
                end = ROUTE['end']
                response = set_location(['developer', 'dvt', 'simulate-location', 'set', '--',
                                         str(end[0]), str(end[1])], end)
                if not response['ok']:
                    PINNED_POINT = end
                    PINNED_ERROR = '已到終點，但固定終點失敗：' + response['message']
                    RETRY_AT = time.monotonic() + 20
            elif PINNED_POINT is not None and (ACTIVE_PROCESS is None or ACTIVE_PROCESS.poll() is not None):
                if time.monotonic() >= RETRY_AT:
                    point = PINNED_POINT
                    response = set_location(['developer', 'dvt', 'simulate-location', 'set', '--',
                                             str(point[0]), str(point[1])], point)
                    if not response['ok']:
                        PINNED_POINT = point
                        PINNED_ERROR = '定位連線中斷，重新連線失敗：' + response['message']
                        RETRY_AT = time.monotonic() + 20
        except Exception as exc:
            PINNED_ERROR = f'定位維持失敗：{exc}'
            RETRY_AT = time.monotonic() + 20
        finally:
            LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def send_data(self, status, content, content_type='application/json; charset=utf-8'):
        data = content if isinstance(content, bytes) else content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/':
            self.send_data(200, (ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        elif self.path == '/api/state':
            self.send_data(200, json.dumps(movement_status(), ensure_ascii=False))
        else:
            self.send_data(404, json.dumps({'error':'找不到頁面'}))

    def do_POST(self):
        global PINNED_POINT, PINNED_ERROR
        if self.path != '/api/run':
            return self.send_data(404, json.dumps({'error':'找不到 API'}))
        try:
            if int(self.headers.get('Content-Length','0')) > 4096:
                raise ValueError('請求過大')
            payload = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            action = payload.get('action')
            if action == 'set':
                lat, lon = float(payload['lat']), float(payload['lon'])
                if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError('經緯度超出範圍')
                args = ['developer','dvt','simulate-location','set','--',str(lat),str(lon)]
            elif action == 'move':
                start = (float(payload['startLat']), float(payload['startLon']))
                end = (float(payload['endLat']), float(payload['endLon']))
                if any(not math.isfinite(value) for value in (*start, *end)) or any(
                    not (-90 <= point[0] <= 90 and -180 <= point[1] <= 180) for point in (start, end)
                ):
                    raise ValueError('起點或終點座標超出範圍')
                args = None
            elif action == 'stop_move':
                args = None
            elif action == 'shutdown':
                args = None
            elif action in COMMANDS:
                args = COMMANDS[action]
            else:
                raise ValueError('不支援的操作')
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return self.send_data(400, json.dumps({'ok':False,'message':str(exc)},ensure_ascii=False))
        if not LOCK.acquire(blocking=False):
            return self.send_data(409, json.dumps({'ok':False,'message':'另一個指令正在執行'},ensure_ascii=False))
        try:
            if action == 'shutdown':
                PINNED_POINT = None
                PINNED_ERROR = ''
                stop_active_process()
                response = {'ok': True, 'message': '控制台已關閉，定位程序也已結束。下次使用請重新執行 start.bat。'}
            elif action == 'set':
                PINNED_POINT = None
                PINNED_ERROR = ''
                response = set_location(args, (lat, lon))
            elif action == 'move':
                response = start_movement(start, end)
            elif action == 'stop_move':
                response = stop_movement()
            else:
                if action == 'clear':
                    PINNED_POINT = None
                    PINNED_ERROR = ''
                    stop_active_process()
                command = [sys.executable, '-m', 'pymobiledevice3', *args]
                result = subprocess.run(command, capture_output=True, text=True,
                                        timeout=CLEAR_TIMEOUT if action == 'clear' else COMMAND_TIMEOUT,
                                        errors='replace')
                output = (result.stdout + '\n' + result.stderr).strip()
                response = {'ok': result.returncode == 0,
                            'message': ('已送出恢復真實定位指令。' if action == 'clear' and result.returncode == 0
                                        else output[-7500:] or ('已完成' if result.returncode == 0 else '指令失敗'))}
            self.send_data(200, json.dumps(response,ensure_ascii=False))
            if action == 'shutdown':
                timer = threading.Timer(0.2, self.server.shutdown)
                timer.daemon = True
                timer.start()
        except subprocess.TimeoutExpired as exc:
            details = b'\n'.join(part for part in (exc.stdout, exc.stderr) if isinstance(part, bytes))
            message = '指令逾時。請確認 USB 連線、裝置已解鎖，然後重試。套件警告不是定位成功的訊號。'
            if details:
                message += '\n\n指令輸出：\n' + details.decode('utf-8', errors='replace')[-3000:]
            self.send_data(200, json.dumps({'ok': False, 'message': message}, ensure_ascii=False))
        except Exception as exc:
            self.send_data(500,json.dumps({'ok':False,'message':str(exc)},ensure_ascii=False))
        finally:
            LOCK.release()

    def log_message(self, format, *args):
        pass


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == 'win32':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


if __name__ == '__main__':
    try:
        server = LocalServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f'無法啟動：連接埠 {PORT} 已被占用。定位控制台可能已在執行。')
        print(exc)
        sys.exit(2 if exc.errno in (errno.EADDRINUSE, 10048) else 1)
    print(f'本機 GPS 控制頁面：http://{HOST}:{PORT}')
    print('保留此視窗開啟即可操作。按 Ctrl+C 結束。')
    threading.Thread(target=maintain_location, daemon=True).start()
    threading.Timer(0.8,lambda: webbrowser.open(f'http://{HOST}:{PORT}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已關閉本機服務。')
    finally:
        stop_active_process()
        server.server_close()
