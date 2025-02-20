# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify
import threading
import time
import requests
from datetime import datetime, timedelta
import json
import logging
from logging.handlers import RotatingFileHandler
import bitget.bitget_api as baseApi
import bitget.consts as bg_constants
from bitget.exceptions import BitgetAPIException

app = Flask(__name__)

# TODO 待办
# 1、测试一下monitor_price的逻辑
# 2、需要补充一个页面，让用户可以配置API和secret，也可以手动停止策略的运行
# 3、在页面中需要展示当前的策略运行情况，比如当前的仓位，当前的挂单，当前的止损单，当前的移动止盈单
# 4、补充处理失败的时候，微信发出告警
# 5、发现一个问题：挂单价格有限制，不能挂离当前价格太远，否则会报错，需要等价格快到了再去挂单

# 配置信息
WX_TOKEN = bg_constants.WX_TOKEN
PRODUCT_TYPE = bg_constants.PRODUCT_TYPE

ip_white_list = bg_constants.IP_WHITE_LIST
baseApi = baseApi.BitgetApi(bg_constants.API_KEY, bg_constants.API_SECRET, bg_constants.API_PASSPHRASE)

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
            send_wx_notification(f'{symbol}|下单失败', f'下单失败，错误: {response}')
            return None
    except BitgetAPIException as e:
        logger.error(f'{symbol}|下单失败，错误: {e}')
        send_wx_notification(f'{symbol}|下单失败', f'下单失败，错误: {e}')
        return None

def query_order(symbol, order_id):
    """查询订单"""
    try:
        params = {}
        params["symbol"] = symbol
        params["productType"] = bg_constants.PRODUCT_TYPE
        params["orderId"] = order_id
        response = baseApi.get("/api/v2/mix/order/detail", params)
        if response['code'] == bg_constants.SUCCESS:
            return response['data']
        else:
            logger.error(f'{symbol}|查询订单失败，错误: {response}')
            return None
    except BitgetAPIException as e:
        logger.error(f'{symbol}|查询订单失败，错误: {e}')
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
            return float(response['data'][0]['total']), response['data'][0]['holdSide']
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

def set_position_mode(pos_mode):
    """设置持仓模式"""
    try:
        params = {}
        params["posMode"] = pos_mode
        params["productType"] = bg_constants.PRODUCT_TYPE
        response = baseApi.post("/api/v2/mix/account/set-position-mode", params)
        if response['code'] == bg_constants.SUCCESS:
            logger.info(f'设置持仓模式成功')
            return None
        else:
            logger.error(f'设置持仓模式失败，错误: {response}')
            return None
    except BitgetAPIException as e:
        logger.error(f'设置持仓模式失败，错误: {e}')
        return None

def batch_cancel_orders(symbol, order_id_list):
    """批量撤销挂单"""
    try:
        params = {}
        params["symbol"] = symbol
        params["marginCoin"] = "USDT"
        params["productType"] = bg_constants.PRODUCT_TYPE
        params["orderIdList"] = order_id_list
        response = baseApi.post("/api/v2/mix/order/batch-cancel-order", params)
        if response['code'] == bg_constants.SUCCESS:
            return response['data']['successList']
        else:
            logger.error(f'{symbol}|批量撤销挂单失败，错误: {response}')
            return None
    except BitgetAPIException as e:
        logger.error(f'{symbol}|批量撤销挂单失败，错误: {e}')
        return None

def get_mark_price(symbol):
    """获取标记价格"""
    try:
        params = {}
        params["symbol"] = symbol
        params["productType"] = bg_constants.PRODUCT_TYPE
        response = baseApi.get("/api/v2/mix/market/ticker", params)
        if response['code'] == bg_constants.SUCCESS:
            return response['data'][0]['markPrice']
        else:
            logger.error(f'{symbol}|获取标记价格失败，错误: {response}')
            return None
    except BitgetAPIException as e:
        logger.error(f'{symbol}|获取标记价格失败，错误: {e}')
        return None

# 设置持仓模式
set_position_mode("one_way_mode")

# 获取币种的精度
try:
    params = {}
    params["productType"] = "USDT-FUTURES"
    exchange_info = baseApi.get("/api/v2/mix/market/contracts", params)
    symbol_tick_size = {}
    for item in exchange_info['data']:
        symbol_tick_size[item['symbol']] = {
            'tick_size': int(item["pricePlace"]),
            'min_qty': int(item["volumePlace"]),
        }
    logger.info(f'获取币种精度成功')
except BitgetAPIException as error:
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
        self.total_usdt = 0
        self.every_zone_usdt = 0
        self.loss_decrease = 0
        self.direction = ""
        self.entry_config = ""
        self.exit_config = ""
        self.pos_for_trail = 0
        self.trail_active_percent = 0
        self.trail_active_price = 0
        self.trail_callback = 0
        self.up_line = 0
        self.down_line = 0
        self.entry_list = []
        self.exit_list = []
        self.paused = False # 是否暂停
        self.running = False # 是否运行
        self.monitor_thread = None # 监控线程
        self.loss_count = 0 # 亏损次数
        self.trail_high_price = 0 # 移动止盈的最高价格
        self.trail_low_price = 999999 # 移动止盈的最低价格
        self.stop_loss_order_id = None # 止损单ID

        logger.info(f'{symbol} GridTrader 初始化完成')


    def update_trading_params(self, data):
        # 当前如果处于运行状态，则无需更改交易参数
        if data['direction'] == self.direction and self.running:
            logger.info(f'{self.symbol} 交易方向未发生变化，无需更新交易参数')
            return

        elif data['direction'] != self.direction:
            self.running = True
            try:
                # 平仓
                close_position(self.symbol)
                # 取消所有挂单
                cancel_all_orders(self.symbol)

                # 更新新的方向的参数
                logger.info(f'更新交易参数: {json.dumps(data, ensure_ascii=False)}')
                self.total_usdt = float(data['total_usdt'])
                self.every_zone_usdt = float(data['every_zone_usdt'])
                self.loss_decrease = float(data['loss_decrease'])
                self.direction = data['direction']
                self.entry_config = data['entry_config']
                self.exit_config = data['exit_config']
                self.pos_for_trail = float(data['pos_for_trail'])
                self.trail_active_percent = float(data['trail_active_price']) # 移动止盈的触发percent
                self.trail_callback = float(data['trail_callback'])
                self.up_line = float(data['up_line'])
                self.down_line = float(data['down_line'])
                self.zone_usdt = self.total_usdt * self.every_zone_usdt # 预期一个区间要投入的金额
                self.trail_high_price = 0 # 移动止盈的最高价格
                self.trail_low_price = 999999 # 移动止盈的最低价格
                self.stop_loss_order_id = None # 止损单ID

                if self.direction == "buy":
                    # ------ 上沿 up_line 100000
                    #  ^
                    #  |
                    #  |
                    # ------ 下沿 down_line 90000
                    self.interval = self.up_line - self.down_line
                    self.trail_active_price = self.down_line + self.interval * self.trail_active_percent
                    # 解析入场配置
                    self.entry_list = []
                    if self.entry_config:
                        entry_configs = self.entry_config.split('|')
                        for config in entry_configs:
                            price_ratio, percent = config.split('_')
                            # 入场价格 = 下轨 + 价格处于区间的百分比 * 区间宽度
                            entry_price = round(self.down_line + float(price_ratio) * 0.01 * self.interval, symbol_tick_size[self.symbol]['tick_size'])
                            entry_percent = float(percent) * 0.01
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
                            exit_price = round(self.down_line + float(price_ratio)*0.01 * self.interval, symbol_tick_size[self.symbol]['tick_size'])
                            exit_percent = float(percent) * 0.01
                            self.exit_list.append({
                                'exit_price': exit_price, # 退出价格
                                'percent': exit_percent,  # 离场资金百分比
                            })
                        logger.info(f'出场配置解析结果: {json.dumps(self.exit_list, ensure_ascii=False)}')

                    # 挂上限价单
                    order_list = []
                    for entry in self.entry_list:
                        order_list.append({
                            "side": "buy",
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

                elif self.direction == "sell":
                    # 做空的时候，因为预期是要往下走的，所以down_line是区间上沿的价格, up_line是区间下沿的价格
                    # ------ 上沿 down_line 100000
                    #  |
                    #  |
                    #  v
                    # ------ 下沿 up_line 90000
                    self.interval = self.down_line - self.up_line
                    self.trail_active_price = self.down_line - self.interval * self.trail_active_percent
                    # 解析入场配置
                    self.entry_list = []
                    if self.entry_config:
                        entry_configs = self.entry_config.split('|')
                        for config in entry_configs:
                            price_ratio, percent = config.split('_')
                            # 入场价格 = 下轨 - 价格处于区间的百分比 * 区间宽度
                            # 做空时下轨是区间上沿的价格
                            entry_price = round(self.down_line - (1 - float(price_ratio) * 0.01) * self.interval, symbol_tick_size[self.symbol]['tick_size'])
                            entry_percent = float(percent) * 0.01
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
                            exit_price = round(self.down_line - (1 - float(price_ratio) * 0.01) * self.interval, symbol_tick_size[self.symbol]['tick_size'])
                            exit_percent = float(percent) * 0.01
                            self.exit_list.append({
                                'exit_price': exit_price, # 退出价格
                                'percent': exit_percent,  # 离场资金百分比
                                'order_id': None # 订单ID
                            })
                        logger.info(f'出场配置解析结果: {json.dumps(self.exit_list, ensure_ascii=False)}')

                    # 挂限价单
                    order_list = []
                    for entry in self.entry_list:
                        order_list.append({
                            "side": "sell",
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
            except Exception as e:
                logger.error(f'{self.symbol} 更新交易参数时发生错误: {str(e)}')
                return None

    def monitor_price(self):
        """监控价格并更新止损"""
        self.is_monitoring = True
        logger.info(f'{self.symbol} 开始价格监控')
        
        while True:
            try:
                # 获取当前仓位和持仓方向
                position, hold_side = get_position(self.symbol)

                # 如果发现止损单和当前仓位不一致，则需要更新止损单
                if position > 0 and self.stop_loss_order_id is None:
                    # 创建止损单
                    self.stop_loss_order_id = place_order(self.symbol, "sell" if self.direction == "buy" else "buy", position, self.down_line, "limit")
                    if self.stop_loss_order_id:
                        logger.info(f"{self.symbol}|止损单已经创建: {self.stop_loss_order_id}")
                    else:
                        logger.error(f"{self.symbol}|止损单创建失败")
                elif self.stop_loss_order_id:
                    # 检查止损单是否已经成交
                    order_detail = query_order(self.symbol, self.stop_loss_order_id)
                    if order_detail and order_detail['state'] == 'filled':
                        # 止损单已经成交，说明该区间的逻辑结束了
                        cancel_all_orders(self.symbol)
                        logger.info(f"{self.symbol}|止损单已经成交，区间逻辑结束")
                    
                # 获取当前所有挂单
                pending_orders = get_pending_orders(self.symbol)
                
                # 创建挂单映射，用于快速查找
                pending_order_map = {}
                if pending_orders:
                    for order in pending_orders:
                        pending_order_map[order['orderId']] = order

                # 检查入场单状态
                for entry in self.entry_list:
                    # 如果入场单ID存在但在当前挂单中找不到，说明可能已成交
                    if entry['order_id'] and entry['order_id'] not in pending_order_map:
                        logger.info(f'{self.symbol} 入场单 {entry["order_id"]} 已成交')
                        order_detail = query_order(self.symbol, entry['order_id'])
                        if order_detail and order_detail['state'] == 'filled':
                            # 清除掉之后，下一次进来如果发现当前的入场单都是live状态，那不需要再去更新出场单
                            self.entry_list.remove(entry)
                            logger.info(f'{self.symbol} 入场单 {entry["order_id"]} 已成交，移除入场单')
                        # 检测到有入场单成交且已经有持仓，更新出场单
                        if position > 0 and order_detail and order_detail['state'] == 'filled':
                            # 取消所有现有的出场挂单
                            exit_orders_to_cancel = [order['orderId'] for order in pending_orders if 
                                                   (self.direction == "buy" and order['side'] == "sell") or
                                                   (self.direction == "sell" and order['side'] == "buy")]
                            if exit_orders_to_cancel:
                                batch_cancel_orders(self.symbol, exit_orders_to_cancel)
                            
                            # 创建新的出场订单
                            new_exit_orders = []
                            for exit_conf in self.exit_list:
                                # 用分批止盈的仓位来设计出场单
                                # 会预留一部分仓位来做移动止盈
                                exit_qty = round(position * (1 - self.pos_for_trail) * exit_conf['percent'], symbol_tick_size[self.symbol]['min_qty'])
                                if exit_qty > 0:
                                    new_exit_orders.append({
                                        "side": "sell" if self.direction == "buy" else "buy",
                                        "price": exit_conf['exit_price'],
                                        "size": exit_qty,
                                        "orderType": "limit"
                                    })
                            
                            if new_exit_orders:
                                ret_list = batch_place_order(self.symbol, new_exit_orders)
                                # TODO 加一下成功与失败的判断
                                for i in range(len(ret_list)):
                                    self.exit_list[i]['order_id'] = ret_list[i]['orderId']
                                # 刚挂完出场单，不可能马上成交，可以等待下一次监测判断
                                continue

                # 检查出场单状态
                for exit_conf in self.exit_list:
                    if exit_conf['order_id'] and exit_conf['order_id'] not in pending_order_map:
                        logger.info(f'{self.symbol} 出场单 {exit_conf["order_id"]} 已成交')
                        order_detail = query_order(self.symbol, exit_conf['order_id'])
                        if order_detail and order_detail['state'] == 'filled':
                            # 成交的单子就会被移除掉
                            self.exit_list.remove(exit_conf)
                            logger.info(f'{self.symbol} 出场单 {exit_conf["order_id"]} 已成交，移除出场单')
                            
                            # 取消所有现有的入场挂单
                            entry_orders_to_cancel = []
                            if pending_orders:
                                entry_orders_to_cancel = [order['orderId'] for order in pending_orders if 
                                                        (self.direction == "buy" and order['side'] == "buy") or
                                                        (self.direction == "sell" and order['side'] == "sell")]
                            if entry_orders_to_cancel:
                                batch_cancel_orders(self.symbol, entry_orders_to_cancel)
                            
                            # 重新计算并设置入场单
                            new_entry_orders = []
                            remaining_position = position  # 当前持仓量
                            
                            for entry in self.entry_list:  # 直接遍历原始列表
                                if remaining_position >= entry['qty']:
                                    # 如果剩余持仓大于等于该入场点应有的持仓量，不需要在此价位补单
                                    remaining_position -= entry['qty']
                                else:
                                    # 需要补单的数量 = 应有持仓量 - 剩余持仓量
                                    need_qty = entry['qty'] - remaining_position
                                    if need_qty > 0:
                                        new_entry_orders.append({
                                            "side": self.direction,
                                            "price": entry['entry_price'],
                                            "size": round(need_qty, symbol_tick_size[self.symbol]['min_qty']),
                                            "orderType": "limit"
                                        })
                                    remaining_position = 0
                            
                            # 批量下新的入场单
                            if new_entry_orders:
                                ret_list = batch_place_order(self.symbol, new_entry_orders)
                                # 更新入场单ID
                                for i, ret in enumerate(ret_list):
                                    self.entry_list[i]['order_id'] = ret['orderId']
                                logger.info(f'{self.symbol} 重新设置入场单成功: {json.dumps(new_entry_orders, ensure_ascii=False)}')

                # 检测当前价格是否已经达到了移动止盈的触发点
                mark_price = get_mark_price(self.symbol)
                if mark_price:
                    mark_price = float(mark_price)
                    if self.direction == "buy":
                        if mark_price < self.down_line:
                            close_position(self.symbol)
                            cancel_all_orders(self.symbol)
                            logger.info(f"{self.symbol}|做多|当前价格已经达到了止损点: {mark_price}")
                        if mark_price > self.trail_active_price:
                            logger.info(f'{self.symbol} 当前价格已经达到了移动止盈的触发点: {mark_price}')
                            if mark_price > self.trail_high_price:
                                self.trail_high_price = mark_price
                        if (self.trail_high_price - mark_price) / mark_price > self.trail_callback:
                            logger.info(f"{self.symbol}|做多|当前价格从最高点回落超过{self.trail_callback}，平仓|区间逻辑结束")
                            # 平仓
                            close_position(self.symbol)
                            cancel_all_orders(self.symbol)
                    elif self.direction == "sell":
                        if mark_price > self.down_line:
                            close_position(self.symbol)
                            cancel_all_orders(self.symbol)
                            logger.info(f"{self.symbol}|做空|当前价格已经达到了止损点: {mark_price}")
                        if mark_price < self.trail_active_price:
                            logger.info(f'{self.symbol} 当前价格已经达到了移动止盈的触发点: {mark_price}')
                            if mark_price < self.trail_low_price:
                                self.trail_low_price = mark_price
                        if (mark_price - self.trail_low_price) / self.trail_low_price > self.trail_callback:
                            logger.info(f"{self.symbol}|做空|当前价格从最低点回升超过{self.trail_callback}，平仓|区间逻辑结束")
                            # 平仓
                            close_position(self.symbol)
                            cancel_all_orders(self.symbol)
                time.sleep(2)  # 每2秒检查一次
                
            except Exception as e:
                logger.error(f'{self.symbol} 监控价格时发生错误: {str(e)}')
                time.sleep(2)
                
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
        
        if symbol not in trading_pairs:
            # 创建或更新 GridTrader 实例
            trading_pairs[symbol] = GridTrader(symbol)
        
        # 设置交易参数
        trading_pairs[symbol].update_trading_params(data)
        
        # logger.info(f'{symbol} 交易参数设置成功')
        return jsonify({"status": "success", "message": f"{symbol} 接收消息成功"})
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
