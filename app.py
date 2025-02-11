# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify
from binance.um_futures import UMFutures as Client
import threading
import time
import requests
from datetime import datetime, timedelta
import json
import logging
from logging.handlers import RotatingFileHandler
from binance.um_futures import UMFutures as Client
from binance.error import ClientError
from config import BINANCE_CONFIG, WX_CONFIG
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os

app = Flask(__name__)

# 配置信息
WX_TOKEN = WX_CONFIG['token']

ip_white_list = BINANCE_CONFIG['ip_white_list']

client = Client(
    BINANCE_CONFIG['key'], 
    BINANCE_CONFIG['secret'], 
    base_url=BINANCE_CONFIG['base_url']
)


def prefix_symbol(s: str) -> str:
    # BINANCE:BTCUSDT.P -> BTC-USDT-SWAP
    # 首先处理冒号，如果存在则取后面的部分
    if ':' in s:
        s = s.split(':')[1]
    
    # 检查字符串是否以".P"结尾并移除
    if s.endswith('.P'):
        s = s[:-2]
    
    return s

def send_wx_notification(title, message):
    """
    发送微信通知
    
    Args:
        title: 通知标题
        message: 通知内容
    """
    try:
        mydata = {
            'text': title,
            'desp': message
        }
        requests.post(f'https://wx.xtuis.cn/{WX_TOKEN}.send', data=mydata)
        logger.info('发送微信消息成功')
    except Exception as e:
        logger.error(f'发送微信消息失败: {str(e)}')

def get_decimal_places(tick_size):
    tick_str = str(float(tick_size))
    if '.' in tick_str:
        return len(tick_str.split('.')[-1].rstrip('0'))
    return 0

# 配置日志
def setup_logger():
    logger = logging.getLogger('grid_trader')
    logger.setLevel(logging.INFO)
    
    # 创建 rotating file handler，最大文件大小为 10MB，保留 5 个备份文件
    handler = RotatingFileHandler('grid_trader.log', maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    return logger

logger = setup_logger()

# 获取币种的精度
try:
    exchange_info = client.exchange_info()['symbols']
    symbol_tick_size = {}
    for item in exchange_info:
        symbol_tick_size[item['symbol']] = {
            'tick_size': get_decimal_places(item['filters'][0]['tickSize']),
            'min_qty': get_decimal_places(item['filters'][1]['minQty']),
        }
except ClientError as error:
    send_wx_notification(f'获取币种精度失败', f'获取币种精度失败，错误: {error}')
    logger.error(
        "Found error. status: {}, error code: {}, error message: {}".format(
            error.status_code, error.error_code, error.error_message
        )
    )

# 创建全局字典来存储不同币种的交易信息
trading_pairs = {}

class GridTrader:
    def __init__(self, symbol):
        self.symbol = prefix_symbol(symbol)
        self.current_grid = 0
        self.grids = []
        self.stop_loss_price = 0
        self.position_qty = 0
        self.initial_price = 0
        self.is_monitoring = False  # 添加监控状态标志
        self.monitor_thread = None  # 添加监控线程对象
        self.stop_loss_order_id = None  # 添加止损单ID
        self.side = ""
        
        logger.info(f'{symbol} GridTrader 初始化完成')
        
    def set_trading_params(self, data):
        logger.info(f'设置交易参数: {json.dumps(data, ensure_ascii=False)}')
        self.initial_price = float(data['price'])  # 当前价格
        
        # 获取持仓数量
        try:
            account_res = client.account(recvWindow=6000)
            for item in account_res['positions']:
                if item['symbol'] == self.symbol:
                    self.position_qty = round(float(item['positionAmt']) * float(data['qty_percent'])/100, symbol_tick_size[self.symbol]['min_qty'])
                    self.side = "BUY" if float(item['positionAmt']) > 0 else "SELL"
                    if self.side == "SELL":
                        self.position_qty = -self.position_qty
                    break
        except ClientError as error:
            send_wx_notification(f'获取持仓数量失败', f'获取持仓数量失败，错误: {error}')
            logger.error(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.error_code, error.error_message
                )
            )
            return
        
        # 解析新的网格格式
        grid_ranges = [x.split('-') for x in data['grid'].split('|')]
        
        # 构建网格
        self.grids = []
        for lower_str, upper_str in grid_ranges:
            lower = float(lower_str)
            upper = float(upper_str)
            size = upper - lower
            if self.side == "BUY":
                self.grids.append({
                    'lower': round(lower, symbol_tick_size[self.symbol]['tick_size']),
                    'upper': round(upper, symbol_tick_size[self.symbol]['tick_size']),
                    'grid_target': round(lower + (size * float(data['grid_target'])/100), symbol_tick_size[self.symbol]['tick_size']),
                    'grid_tp': round(lower + (size * float(data['grid_tp'])/100), symbol_tick_size[self.symbol]['tick_size']),
                    'break_tp': round(lower + (size * float(data['break_tp'])/100), symbol_tick_size[self.symbol]['tick_size']),
                    'activated_target_1': False, # 网格下半部分的出场点是否被触发   
                    'activated_target_2': False, # 网格上半部分的出场点是否被触发
                    'size': size
                })

            else:
                self.grids.append({
                    'lower': round(lower, symbol_tick_size[self.symbol]['tick_size']),
                    'upper': round(upper, symbol_tick_size[self.symbol]['tick_size']),
                    'grid_target': round(upper - (size * float(data['grid_target'])/100), symbol_tick_size[self.symbol]['tick_size']),
                    'grid_tp': round(upper - (size * float(data['grid_tp'])/100), symbol_tick_size[self.symbol]['tick_size']),
                    'break_tp': round(upper - (size * float(data['break_tp'])/100), symbol_tick_size[self.symbol]['tick_size']),
                    'activated_target_1': False, # 网格下半部分的出场点是否被触发   
                    'activated_target_2': False, # 网格上半部分的出场点是否被触发
                    'size': size
                })

        
        
        if self.side == "BUY":
            self.stop_loss_price = round(self.grids[0]['lower'], symbol_tick_size[self.symbol]['tick_size'])
        else:
            self.stop_loss_price = round(self.grids[0]['upper'], symbol_tick_size[self.symbol]['tick_size'])
        # 把止损单通过接口捞出来，如果没有止损单，则以当前网格的下线作为止损，挂个止损单
        try:
            order_res = client.get_orders(symbol=self.symbol, recvWindow=2000)
            if len(order_res) > 0:
                logger.info(f'{self.symbol} 已存在止损单，无需处理')
                self.stop_loss_order_id = order_res[0]['orderId']
            else:
                logger.info(f'{self.symbol} 不存在止损单，挂止损单')
                # 设置初始止损价格
                # 获取持仓数量
                
                self.place_stop_loss_order(self.stop_loss_price)
        except ClientError as error:
            logger.error(f'获取止损单失败，错误: {error}')

        logger.info(f'{self.symbol} 网格设置完成|网格情况: {json.dumps(self.grids, ensure_ascii=False)}')

    def place_stop_loss_order(self, price):
        """下止损单"""
        logger.info(f'{self.symbol} 下止损单，价格: {price}, 数量: {self.position_qty}')
        if self.stop_loss_order_id:
            logger.info(f'{self.symbol} 止损单已存在，先撤销，ID: {self.stop_loss_order_id}')
            # 撤销之前的止损单
            client.cancel_order(symbol=self.symbol, orderId=self.stop_loss_order_id,recvWindow=2000)
        # 调用Binance API下止损单
        # 记录止损单ID
        try:
            response = client.new_order(
                symbol=self.symbol,
                side="SELL" if self.side == "BUY" else "BUY",
                type="STOP",
                quantity=self.position_qty,
                timeInForce="GTC",
                price=price,
                stopPrice=price,
            )
            logger.info(response)
            if response['orderId'] is not None:
                self.stop_loss_order_id = response['orderId']
                logger.info(f'止损单已创建，ID: {self.stop_loss_order_id}')
                send_wx_notification(f'{self.symbol} 止损单已创建', f'止损单已创建，ID: {self.stop_loss_order_id}')
            else:
                logger.error(f'止损单创建失败，响应: {response}')
                send_wx_notification(f'{self.symbol} 止损单创建失败', f'止损单创建失败，响应: {response}')

        except ClientError as error:
            send_wx_notification(f'{self.symbol} 止损单创建失败', f'止损单创建失败，错误: {error}')
            logger.error(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.error_code, error.error_message
                )
            )

    def update_stop_loss(self, current_price):
        """更新止损价格"""
        for i, grid in enumerate(self.grids):
            if self.side == "BUY":
                if current_price > grid['lower'] and current_price < grid['upper']:
                    self.current_grid = i
                # 来到网格的上半部分，上移止损位置到网格的sl_price位置
                if current_price >= grid['grid_target'] and not grid['activated_target_1']:
                    grid['activated_target_1'] = True # 标记为已激活
                    # 更新止损价格为止盈价格
                    self.stop_loss_price = grid['grid_tp']
                    self.place_stop_loss_order(self.stop_loss_price)
                    logger.info(f'{self.symbol}做多|价格来到网格{i+1}的上半部分，设置止盈价格: {self.stop_loss_price}')
                    send_wx_notification(f'{self.symbol}|网格{i+1}上移止损', f'价格来到网格{i+1}的上半部分，设置止盈价格: {self.stop_loss_price}')
                    break
                # 当价格突破网格上限时
                if current_price >= grid['upper'] and not grid['activated_target_2']:
                    grid['activated_target_2'] = True
                    # 更新止损价格为止盈价格
                    self.stop_loss_price = grid['break_tp']
                    self.place_stop_loss_order(self.stop_loss_price)
                    logger.info(f'{self.symbol}做多|价格突破网格{i+1}上限，设置止盈价格: {self.stop_loss_price}')
                    send_wx_notification(f'{self.symbol}做多|价格突破网格{i+1}上限', f'价格突破网格{i+1}上限，设置止损价格: {self.stop_loss_price}')
                    break

            else:
                # 做空的逻辑
                if current_price < grid['upper'] and current_price > grid['lower']:
                    self.current_grid = i
                # 来到网格的下半部分，下移止损位置到网格1的sl_price位置
                if current_price <= grid['grid_target'] and not grid['activated_target_1']:
                    grid['activated_target_1'] = True # 标记为已激活
                    # 更新止损价格为止盈价格
                    self.stop_loss_price = grid['grid_tp']
                    self.place_stop_loss_order(self.stop_loss_price)
                    logger.info(f'{self.symbol}做空| 价格来到网格{i+1}的下半部分，设置止盈价格: {self.stop_loss_price}')
                    send_wx_notification(f'{self.symbol}做空|网格{i+1}下移止损', f'价格来到网格{i+1}的下半部分，设置止盈价格: {self.stop_loss_price}')
                    break
                # 当价格突破网格下限时
                if current_price <= grid['lower'] and not grid['activated_target_2']:
                    grid['activated_target_2'] = True
                    # 更新止损价格为止盈价格
                    self.stop_loss_price = grid['break_tp']
                    self.place_stop_loss_order(self.stop_loss_price)
                    logger.info(f'{self.symbol}做空|价格突破网格{i+1}下限，设置止盈价格: {self.stop_loss_price}')
                    send_wx_notification(f'{self.symbol}做空|价格突破网格{i+1}下限', f'价格突破网格{i+1}下限，设置止损价格: {self.stop_loss_price}')
                    break

    def monitor_price(self):
        """监控价格并更新止损"""
        self.is_monitoring = True
        logger.info(f'{self.symbol} 开始价格监控')
        
        while self.is_monitoring:
            try:
                # 检查止损单状态
                if self.stop_loss_order_id:
                    try:
                        order_status = client.query_order(
                            symbol=self.symbol,
                            orderId=self.stop_loss_order_id
                        )
                        # 如果止损单已执行完成，停止监控
                        if order_status['status'] == 'CANCELED' or order_status['status'] == 'FILLED':
                            logger.info(f'{self.symbol} 止损单已执行，停止监控')
                            send_wx_notification(f'{self.symbol} 止损单已执行', f'止损单已执行，停止监控')
                            self.stop_monitoring()
                            break
                    except Exception as e:
                        logger.error(f'查询止损单状态失败: {str(e)}')
                # 获取当前价格
                current_price = float(client.mark_price(self.symbol)['markPrice'])
                
                # 更新止损价格
                self.update_stop_loss(current_price)

                time.sleep(2)  # 每2秒检查一次
            except Exception as e:
                logger.error(f'{self.symbol} 监控价格时发生错误: {str(e)}')
                time.sleep(2)  # 发生错误时也等待2秒
                
    def stop_monitoring(self):
        """停止价格监控"""
        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join()
            logger.info(f'{self.symbol} 停止价格监控')

class ConfigFileHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_modified = 0
    
    def on_modified(self, event):
        if event.src_path.endswith('config.py'):
            # 防止重复触发
            current_time = time.time()
            if current_time - self.last_modified < 1:  # 1秒内的修改忽略
                return
            self.last_modified = current_time
            
            logger.info("检测到配置文件变更，重新加载配置...")
            try:
                # 重新加载配置模块
                import importlib
                import config
                importlib.reload(config)
                
                global WX_TOKEN, ip_white_list, client
                WX_TOKEN = config.WX_CONFIG['token']
                ip_white_list = config.BINANCE_CONFIG['ip_white_list']
                client = Client(
                    config.BINANCE_CONFIG['key'],
                    config.BINANCE_CONFIG['secret'],
                    base_url=config.BINANCE_CONFIG['base_url']
                )
                logger.info("配置文件重新加载成功")
                send_wx_notification("配置更新", "配置文件已成功重新加载")
            except Exception as e:
                logger.error(f"重新加载配置文件失败: {str(e)}")
                send_wx_notification("配置更新失败", f"重新加载配置文件时发生错误: {str(e)}")

def start_config_monitor():
    event_handler = ConfigFileHandler()
    observer = Observer()
    # 监控配置文件所在的目录
    config_path = os.path.dirname(os.path.abspath(__file__))
    observer.schedule(event_handler, config_path, recursive=False)
    observer.start()
    logger.info("配置文件监控已启动")

# {
#   "symbol": "BTCUSDT", // 币种
# 	"qty_percent": 50, // 用于决定平仓数量。比如我手上有1000USDT的BTC，
#                       50代表我只要有50%的仓位用于该平仓的逻辑。剩下的50%不要去动它
# 	"price": 100000, // 当前的价格
# 	"grid": "96000-97000|97000-98000|98000-99000", // 代表网格的大小。第一个网格则为[96000,97000]，第二个网格为[97000,98000]，
#                               第三个网格为[98000,99000]，最多为三个网格
# 	"grid_target": 75, // 触达到网格的75%位置，则设置止损位到grid_tp的位置
# 	"grid_tp": 20, // 网格下半部分的止盈位置
# 	"break_tp": 70, // 当价格突破网格的上线时，设置一个出场点在网格的70%的位置。
# }
# 
@app.route('/message', methods=['POST'])
def handle_message():
    try:
        data = request.get_json()
        symbol = data['symbol']
        logger.info(f'收到 {symbol} 的新交易参数请求: {json.dumps(data, ensure_ascii=False)}')
        
        # 检查该币种是否已在监控中
        if symbol in trading_pairs and trading_pairs[symbol].is_monitoring:
            logger.warning(f'{symbol} 已经处于监控状态')
            return jsonify({
                "status": "error", 
                "message": f"{symbol} 已经处于监控状态，请先停止现有监控后再重新设置"
            })
        
        # 如果该币种已存在但未在监控中，先停止之前的监控线程
        if symbol in trading_pairs:
            trading_pairs[symbol].stop_monitoring()
        
        # 创建或更新 GridTrader 实例
        trading_pairs[symbol] = GridTrader(symbol)
        
        # 设置交易参数
        trading_pairs[symbol].set_trading_params(data)
        
        # 立即设置初始止损单
        # 将挂止损单的操作上移到set_trading_params中
        # trading_pairs[symbol].place_stop_loss_order(trading_pairs[symbol].stop_loss_price)
        
        # 启动价格监控线程
        trading_pairs[symbol].monitor_thread = threading.Thread(
            target=trading_pairs[symbol].monitor_price
        )
        trading_pairs[symbol].monitor_thread.daemon = True
        trading_pairs[symbol].monitor_thread.start()
        
        logger.info(f'{symbol} 交易参数设置成功')
        return jsonify({"status": "success", "message": f"{symbol} 交易参数设置成功"})
    except Exception as e:
        logger.error(f'设置交易参数失败: {str(e)}')
        return jsonify({"status": "error", "message": str(e)})

def send_wx_message():
    """发送微信消息"""
    while True:
        try:
            # 获取当前时间
            current_hour = datetime.now().hour
            # 获取当前分钟
            current_minute = datetime.now().minute
            # 只在整点0分时发送消息
            if current_minute != 0:
                time.sleep(30)  # 如果不是整点,休眠1分钟后继续检查
                continue
            # 只在指定时间点发送消息
            if current_hour in [0, 4, 8, 12, 16, 20]:
                # 为每个交易对生成状态信息
                status_messages = []
                balance = 0
                # 从Binance获取实时数据
                try:
                    response = client.balance(recvWindow=6000)
                    for item in response:
                        if item['asset'] == 'USDT':
                            balance = item['balance']
                            break
                except ClientError as error:
                    logger.error(
                        "Found error. status: {}, error code: {}, error message: {}".format(
                            error.status_code, error.error_code, error.error_message
                        )
                    )
                for symbol, trader in trading_pairs.items():
                    if trader.is_monitoring:
                        current_price = client.mark_price(symbol)['markPrice']
                        status_messages.append(f"""
                                            {symbol} 交易状态:
                                            当前币种价格: {current_price}
                                            当前止损价格: {trader.stop_loss_price}
                                            处于第几个网格: 第{trader.current_grid + 1}网格
                                            当前网格大小: {trader.grids[trader.current_grid]['size']}
                                            当前持仓数量: {trader.position_qty}
                                            当前持仓方向: {trader.side}
                                            当前网格边界: {trader.grids[trader.current_grid]['lower']} - {trader.grids[trader.current_grid]['upper']}
                                            """)
                    else:
                        current_price = 0
                    
                
                message = "\n".join(status_messages)+f"\n当前账户余额: {balance}\n" + f"\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                mydata = {
                    'text': '交易状态定时报告',
                    'desp': message
                }
                requests.post(f'https://wx.xtuis.cn/{WX_TOKEN}.send', data=mydata)
                logger.info('发送微信消息成功')
            
            # 休眠到下一个小时
            next_hour = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            sleep_seconds = (next_hour - datetime.now()).total_seconds()
            time.sleep(sleep_seconds)
            
        except Exception as e:
            logger.error(f'发送微信消息失败: {str(e)}')
            time.sleep(60)  # 发生错误时等待1分钟后重试



@app.before_request
def before_req():
    logger.info(request.json)
    if request.json is None:
        return jsonify({'error': '请求体不能为空'}), 400
    if request.remote_addr not in ip_white_list:
        logger.info(f'ipWhiteList: {ip_white_list}')
        logger.info(f'ip is not in ipWhiteList: {request.remote_addr}')
        return jsonify({'error': 'ip is not in ipWhiteList'}), 403


if __name__ == '__main__':
    # 启动配置文件监控
    start_config_monitor()
    
    # 启动定时发送消息的线程
    message_thread = threading.Thread(target=send_wx_message)
    message_thread.daemon = True
    message_thread.start()
    
    # 启动Flask服务
    app.run(host='0.0.0.0', port=80)
