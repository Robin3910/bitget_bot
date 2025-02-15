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
from config import EXCHANGE_CONFIG, WX_CONFIG
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
import bitget.bitget_api as baseApi
import bitget.consts as bg_constants
from bitget.exceptions import BitgetAPIException

app = Flask(__name__)

# 配置信息
WX_TOKEN = bg_constants.WX_TOKEN
PRODUCT_TYPE = bg_constants.PRODUCT_TYPE

ip_white_list = bg_constants.IP_WHITE_LIST
baseApi = baseApi.BitgetApi(bg_constants.API_KEY, bg_constants.API_SECRET, bg_constants.API_PASSPHRASE)
client = Client(
    bg_constants.API_KEY, 
    bg_constants.API_SECRET, 
)

# 对币种信息预处理
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
            'title': title,
            'desp': message
        }
        requests.post(f'https://sctapi.ftqq.com/{WX_TOKEN}.send', data=mydata)
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
    logger = logging.getLogger('bg_bot')
    logger.setLevel(logging.INFO)
    
    # 创建 rotating file handler，最大文件大小为 10MB，保留 5 个备份文件
    handler = RotatingFileHandler('bg_bot.log', maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    return logger

logger = setup_logger()

# 获取币种的精度
try:
    params = {}
    # params["symbol"] = "BTCUSDT"
    params["productType"] = "USDT-FUTURES"
    exchange_info = baseApi.get("/api/v2/mix/market/contracts", params)
    symbol_tick_size = {}
    for item in exchange_info['data']:
        symbol_tick_size[item['symbol']] = {
            'tick_size': item["pricePlace"],
            'min_qty': item["volumePlace"],
        }
except ClientError as error:
    send_wx_notification(f'获取币种精度失败', f'获取币种精度失败，错误: {error}')
    logger.error(
        "Found error. status: {}, error code: {}, error message: {}".format(
            error.status_code, error.error_code, error.error_message
        )
    )

def place_order(symbol, side, qty, price, order_type="limit"):
    """下单"""
    try:
        params = {}
        params["symbol"] = symbol
        params["marginCoin"] = "USDT"
        params["marginMode"] = "crossed"
        params["productType"] = bg_constants.PRODUCT_TYPE
        params["side"] = side
        params["orderType"] = order_type
        params["price"] = price
        params["size"] = qty
        response = baseApi.post("/api/v2/mix/order/place-order", params)
        if response['code'] == bg_constants.SUCCESS:
            return response['data']['orderId']
        else:
            logger.error(f'{symbol}|下单失败，错误: {response}')
            return None
    except BitgetAPIException as e:
        logger.error(f'{symbol}|下单失败，错误: {e}')
        return None

def close_position(symbol):
    """平仓"""
    try:
        params = {}
        params["symbol"] = symbol
        params["productType"] = bg_constants.PRODUCT_TYPE
        response = baseApi.post("/api/v2/mix/order/close-positions", params)
        return response
    except BitgetAPIException as e:
        logger.error(f'{symbol}|平仓失败，错误: {e}')
        return None

def get_position(symbol):
    """获取仓位"""
    try:
        params = {}
        params["symbol"] = symbol
        params["productType"] = bg_constants.PRODUCT_TYPE
        params["marginCoin"] = "USDT"
        response = baseApi.get("/api/v2/mix/position/single-position", params)
        if response['code'] == bg_constants.SUCCESS and len(response['data']) > 0:
            return response['data'][0]['total'], response['data'][0]['holdSide']
        else:
            logger.error(f'{symbol}|无仓位: {response}')
            return 0, None
    except BitgetAPIException as e:
        logger.error(f'{symbol}|获取仓位失败，错误: {e}')
        return 0

def batch_place_order(symbol, order_list):
    """批量下单"""
    try:
        params = {}
        params["symbol"] = symbol
        params["marginCoin"] = "USDT"
        params["marginMode"] = "crossed"
        params["productType"] = bg_constants.PRODUCT_TYPE
        params["orderList"] = order_list
        response = baseApi.post("/api/v2/mix/order/batch-place-order", params)
        if response['code'] == bg_constants.SUCCESS:
            return response['data']['successList']
        else:
            logger.error(f'{symbol}|批量下单失败，错误: {response}')
            return None
    except BitgetAPIException as e:
        logger.error(f'{symbol}|批量下单失败，错误: {e}')
        return None

def get_pending_orders(symbol):
    """获取挂单信息"""
    try:
        params = {}
        params["symbol"] = symbol
        params["productType"] = bg_constants.PRODUCT_TYPE
        response = baseApi.get("/api/v2/mix/order/orders-pending", params)
        if response['code'] == bg_constants.SUCCESS:
            return response['data']["entrustedList"]
        else:
            logger.error(f'{symbol}|获取挂单信息失败，错误: {response}')
            return None
    except BitgetAPIException as e:
        logger.error(f'{symbol}|获取挂单信息失败，错误: {e}')
        return None

def cancel_order(symbol, order_id):
    try:
        params = {}
        params['symbol'] = symbol
        params["productType"] = bg_constants.PRODUCT_TYPE
        params['orderId'] = order_id
        response = baseApi.post("/api/v2/mix/order/cancel-order", params)
        return response
    except BitgetAPIException as e:
        logger.error(f'{symbol}|取消挂单失败，错误: {e}')
        return None

def cancel_all_orders(symbol):
    try:
        params = {}
        params['symbol'] = symbol
        params["productType"] = bg_constants.PRODUCT_TYPE
        response = baseApi.post("/api/v2/mix/order/cancel-all-orders", params)
        if response['code'] == bg_constants.SUCCESS:
            logger.info(f'{symbol}|撤销所有挂单成功')
            return None
        else:
            logger.error(f'{symbol}|撤销所有挂单失败，错误: {response}')
            return None
    except BitgetAPIException as e:
        logger.error(f'{symbol}|撤销所有挂单失败，错误: {e}')
        return None

# 创建全局字典来存储不同币种的交易信息
trading_pairs = {}

class GridTrader:
    def __init__(self, symbol):
        self.symbol = prefix_symbol(symbol)
        self.total_usdt = 0
        self.every_zone_usdt = 0
        self.loss_decrease = 0
        self.direction = ""
        self.entry_config = ""
        self.exit_config = ""
        self.pos_for_trail = 0
        self.trail_active_price = 0
        self.trail_callback = 0
        self.up_line = 0
        self.down_line = 0
        self.entry_list = []
        self.exit_list = []
        self.paused = False # 是否暂停
        self.running = False # 是否运行
        self.monitor_thread = None # 监控线程

        logger.info(f'{symbol} GridTrader 初始化完成')


    def update_trading_params(self, data):
        if data['direction'] == self.direction:
            logger.info(f'{self.symbol} 交易方向未发生变化，无需更新交易参数')
            return
        elif data['direction'] == "wait":
            logger.info(f'{self.symbol} 交易方向为等待，无需更新交易参数')
            self.paused = True
            return
        elif data['direction'] != self.direction and self.direction != "wait":
            # 平仓
            close_position(self.symbol)
            # 取消所有挂单
            cancel_all_orders(self.symbol)

            # 更新新的方向的参数
            logger.info(f'更新交易参数: {json.dumps(data, ensure_ascii=False)}')
            self.total_usdt = float(data['total_usdt'])
            self.every_zone_usdt = float(data['every_zone_usdt'])
            self.zone_usdt = self.total_usdt * self.every_zone_usdt # 预期一个区间要投入的金额
            self.loss_decrease = float(data['loss_decrease'])
            self.direction = data['direction']
            self.entry_config = data['entry_config']
            self.exit_config = data['exit_config']
            self.pos_for_trail = float(data['pos_for_trail'])
            self.trail_active_price = float(data['trail_active_price'])
            self.trail_callback = float(data['trail_callback'])
            self.up_line = float(data['up_line'])
            self.down_line = float(data['down_line'])

            if self.direction == "BUY":
                self.interval = self.up_line - self.down_line
                # 解析入场配置
                self.entry_list = []
                if self.entry_config:
                    entry_configs = self.entry_config.split('|')
                    for config in entry_configs:
                        price_ratio, percent = config.split('_')
                        # 入场价格 = 下轨 + 价格处于区间的百分比 * 区间宽度
                        entry_price = round(self.down_line + float(price_ratio) * self.interval, symbol_tick_size[self.symbol]['tick_size'])
                        entry_percent = float(percent)
                        entry_zone_usdt = self.zone_usdt * entry_percent
                        entry_qty = round(entry_zone_usdt / entry_price, symbol_tick_size[self.symbol]['min_qty'])
                        self.entry_list.append({
                            'entry_price': entry_price, # 入场价格
                            'percent': entry_percent,  # 投入资金百分比
                            'zone_usdt': entry_zone_usdt, # 投入资金
                            "qty": entry_qty, # 投入数量
                            "order_id": None # 订单ID
                        })
                    logger.info(f'入场配置解析结果: {json.dumps(self.entry_list, ensure_ascii=False)}')
                
                # 解析出场配置
                self.exit_list = []
                if self.exit_config:
                    exit_configs = self.exit_config.split('|')
                    for config in exit_configs:
                        price_ratio, percent = config.split('_')
                        exit_price = round(self.down_line + float(price_ratio) * self.interval, symbol_tick_size[self.symbol]['tick_size'])
                        exit_percent = float(percent)
                        self.exit_list.append({
                            'exit_price': exit_price, # 退出价格
                            'percent': exit_percent,  # 离场资金百分比
                        })
                    logger.info(f'出场配置解析结果: {json.dumps(self.exit_list, ensure_ascii=False)}')

                # 挂上限价单
                order_list = []
                for entry in self.entry_list:
                    order_list.append({
                        "side": "BUY",
                        "price": entry['entry_price'],
                        "size": entry['qty'],
                        "orderType": "limit"
                    })
                ret_list = batch_place_order(self.symbol, order_list)
                for i in range(len(ret_list)):
                    self.entry_list[i]['order_id'] = ret_list[i]['orderId']



                # 还需要不断监控当前的成交情况，用一个map来记录一下
                # 如果成交了，更新map的信息
                # 如果有仓位离场了，则价格再次下跌的时候要补齐仓位
                # 每次成交了一个仓位，就需要更新一下未来的离场限价单，因为持仓更新，未来需要离场的仓位变大了


                # 存在一个问题：离场了一部分仓位，价格下跌后要补仓多少呢
                # 肯定是先补齐当前价格的仓位，如果当前价格的仓位已经满足了，那就无需再补了

            elif self.direction == "SELL":
                # TODO 卖出方向的逻辑
                self.interval = self.down_line - self.up_line
                # 解析入场配置
                self.entry_list = []
                if self.entry_config:
                    entry_configs = self.entry_config.split('|')
                    for config in entry_configs:
                        price_ratio, percent = config.split('_')
                        # 入场价格 = 下轨 - 价格处于区间的百分比 * 区间宽度
                        # 做空时下轨是区间上沿的价格
                        entry_price = round(self.down_line - float(price_ratio) * self.interval, symbol_tick_size[self.symbol]['tick_size'])
                        entry_percent = float(percent)
                        entry_zone_usdt = self.zone_usdt * entry_percent
                        entry_qty = round(entry_zone_usdt / entry_price, symbol_tick_size[self.symbol]['min_qty'])
                        self.entry_list.append({
                            'entry_price': entry_price, # 入场价格
                            'percent': entry_percent,  # 投入资金百分比
                            'zone_usdt': entry_zone_usdt, # 投入资金
                            "qty": entry_qty, # 投入数量
                            "order_id": None # 订单ID
                        })
                    logger.info(f'入场配置解析结果: {json.dumps(self.entry_list, ensure_ascii=False)}')
                
                # 解析出场配置
                self.exit_list = []
                if self.exit_config:
                    exit_configs = self.exit_config.split('|')
                    for config in exit_configs:
                        price_ratio, percent = config.split('_')
                        exit_price = round(self.down_line - float(price_ratio) * self.interval, symbol_tick_size[self.symbol]['tick_size'])
                        exit_percent = float(percent)
                        self.exit_list.append({
                            'exit_price': exit_price, # 退出价格
                            'percent': exit_percent,  # 离场资金百分比
                        })
                    logger.info(f'出场配置解析结果: {json.dumps(self.exit_list, ensure_ascii=False)}')

                # 挂限价单
                order_list = []
                for entry in self.entry_list:
                    order_list.append({
                        "side": "SELL",
                        "price": entry['entry_price'],
                        "size": entry['qty'],
                        "orderType": "limit"
                    })
                ret_list = batch_place_order(self.symbol, order_list)
                for i in range(len(ret_list)):
                    self.entry_list[i]['order_id'] = ret_list[i]['orderId']

            # 开启一个新的线程来监控成交情况
            if self.monitor_thread is None:
                self.monitor_thread = threading.Thread(target=self.monitor_price)
                self.monitor_thread.start()


    def monitor_price(self):
        """监控价格并更新止损"""
        self.is_monitoring = True
        logger.info(f'{self.symbol} 开始价格监控')
        
        while True:
            try:
                if self.paused:
                    time.sleep(20)
                    continue
                # 检查当前仓位情况
                # 先获取一下仓位
                position, hold_side = get_position(self.symbol)
                if position > 0 and hold_side == "long":
                    logger.info(f'{self.symbol} 当前仓位: {position}')
                    order_list = []
                    for entry in self.entry_list:
                        if entry['order_id'] is not None:
                            order_list.append(entry['order_id'])

                    # 检查挂的入场单成交了多少
                    pending_orders = get_pending_orders(self.symbol)
                    if pending_orders:
                        for order in pending_orders:
                            if order['side'] == "buy":
                                if order['status'] == "filled":
                                    logger.info(f'{self.symbol} 入场单成交: {order}')

                    # 根据入场情况设置出场订单
                elif position > 0 and hold_side == "short":
                    pass

                elif position == 0:
                    # 无仓位的时候，需要检查一下入场单是否都挂好了
                    pending_orders = get_pending_orders(self.symbol) # 获取该币种所有挂单
                    if pending_orders:
                        # 记录已匹配的订单和entry
                        matched_orders = set()
                        matched_entries = set()
                        
                        # 遍历所有挂单，检查是否与entry_list匹配
                        for order in pending_orders:
                            if order['side'] == "buy":
                                order_price = float(order['price'])
                                # 遍历entry_list寻找匹配项
                                for entry in self.entry_list:
                                    price_diff_ratio = abs(order_price - entry['entry_price']) / entry['entry_price']
                                    if price_diff_ratio <= 0.005:  # 价格差在0.5%以内
                                        matched_orders.add(order['orderId'])
                                        matched_entries.add(entry['entry_price'])
                                        entry['order_id'] = order['orderId']
                                        break
                        
                        # 取消不在entry_list中的订单
                        for order in pending_orders:
                            if order['side'] == "buy" and order['orderId'] not in matched_orders:
                                logger.info(f'{self.symbol} 取消不匹配的订单: {order["orderId"]}')
                                cancel_order(self.symbol, order['orderId'])
                        
                        # 补充缺失的入场订单
                        new_orders = []
                        for entry in self.entry_list:
                            if entry['entry_price'] not in matched_entries:
                                new_orders.append({
                                    "side": "BUY",
                                    "price": entry['entry_price'],
                                    "size": entry['qty'],
                                    "orderType": "limit"
                                })
                        
                        if new_orders:
                            logger.info(f'{self.symbol} 补充缺失的入场订单: {json.dumps(new_orders, ensure_ascii=False)}')
                            ret_list = batch_place_order(self.symbol, new_orders)
                            if ret_list:
                                for i, ret in enumerate(ret_list):
                                    for entry in self.entry_list:
                                        if entry['entry_price'] == float(new_orders[i]['price']):
                                            entry['order_id'] = ret['orderId']
                                            break
                    else:
                        # 如果没有挂单，则重新挂入场单
                        order_list = [{
                            "side": "BUY",
                            "price": entry['entry_price'],
                            "size": entry['qty'],
                            "orderType": "limit"
                        } for entry in self.entry_list]
                        ret_list = batch_place_order(self.symbol, order_list)
                        if ret_list:
                            for i, ret in enumerate(ret_list):
                                self.entry_list[i]['order_id'] = ret['orderId']

                time.sleep(2)  # 每2秒检查一次
            except Exception as e:
                logger.error(f'{self.symbol} 监控价格时发生错误: {str(e)}')
                time.sleep(2)  # 发生错误时也等待2秒
                
    def stop_monitoring(self):
        """停止价格监控"""
        if self.monitor_thread:
            self.monitor_thread.join()
            logger.info(f'{self.symbol} 停止价格监控')


# {
#   "symbol": "BTCUSDT", // 币种
#   "total_usdt": 10000, // 总保证金
# 	"every_zone_usdt": 0.02, // 每次区间投入的金额
#   "loss_decrease": 0.25, // 每次区间亏损后，下一次需要降低多少比例的区间投入额
# 	"direction": "buy/sell", // 交易方向
#   "entry_config": "", // 入场配置
#   "exit_config": "", // 出场配置
#   "pos_for_trail": "", // 预留多少x%的仓位用于动态止盈
#   "trail_active_price": 0.6, // 当价格触达区间x%时，开始动态止盈
#   "trail_callback": 0.1, // 当价格从高点回落10%的时候，止盈出场
#   "up_line": 0, // 上轨
#   "down_line": 0, // 下轨
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

    # 启动Flask服务
    app.run(host='0.0.0.0', port=80)
