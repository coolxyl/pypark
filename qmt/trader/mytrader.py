import logging
import os
from typing import Optional, Dict, Any

import pandas as pd

import qmt.xtquant.xttrader as xt_trader
import qmt.xtquant.xttype as xt_type
import qmt.xtquant.xtconstant as xt_const
import datetime

logger = logging.getLogger(__name__)

# 全局交易 API 实例
trade_api: Optional['CustomTradeAPI'] = None

def get_tradeapi():
    """获取全局交易 API 实例（单例模式）"""
    global trade_api
    if trade_api is None:
        trade_api = CustomTradeAPI()
    return trade_api

class CustomCallback(xt_trader.XtQuantTraderCallback):

    def __init__(self):
        super().__init__()
        self.connected = False
        # 用户自定义回调
        self.order_callback = None
        self.trade_callback = None
        self.error_callback = None
        pass

    def set_callbacks(self, order_callback=None, trade_callback=None, error_callback=None):
        """设置用户回调函数"""
        self.order_callback = order_callback
        self.trade_callback = trade_callback
        self.error_callback = error_callback

    def on_connected(self):
        """连接成功"""
        self.connected = True

    def on_disconnected(self):
        """连接断开"""
        self.connected = False

    def on_stock_order(self, order):
        """
        :param order: XtOrder对象
        :return:
        """
        # 调用用户回调
        if self.order_callback:
            try:
                self.order_callback(order)
            except Exception as e:
                logger.error(f"用户委托回调异常: {e}")

    def on_stock_trade(self, trade):
        """
        :param trade: XtTrade对象
        :return:
        """
        # 调用用户回调
        if self.trade_callback:
            try:
                self.trade_callback(trade)
            except Exception as e:
                logger.error(f"用户成交回调异常: {e}")

    def on_stock_position(self, position):
        """
        :param position: XtPosition对象
        :return:
        """
        pass

    def on_order_error(self, order_error):
        """
        :param order_error: XtOrderError 对象
        :return:
        """
        logger.error(f'委托错误 {order_error.error_msg},{self.error_callback}')
        # 调用用户回调
        if self.error_callback:
            try:
                self.error_callback(order_error)
            except Exception as e:
                logger.error(f"用户错误回调异常: {e}")


class CustomTradeAPI:
    """
      对 xt_trader 做一个简单的封装
    """
    pass

    def __init__(self):
        self.trader = None
        self.callback = None
        self.accounts = {}
        self._session_id = None

    def connect(self, userdata_path: str, session_id: str = None) -> bool:

        try:
            if session_id:
                self._session_id = session_id

            # 处理路径
            userdata_path = os.path.normpath(userdata_path)
            if not os.path.exists(userdata_path):
                logger.error(f"userdata 路径不存在：{userdata_path}")
                return False

            # 保存已设置的回调（如果有）
            old_callbacks = None
            if self.callback:
                old_callbacks = {
                    'order': getattr(self.callback, 'order_callback', None),
                    'trade': getattr(self.callback, 'trade_callback', None),
                    'error': getattr(self.callback, 'error_callback', None)
                }

            # 创建回调对象
            self.callback = CustomCallback()

            # 恢复之前的回调设置
            if old_callbacks:
                self.callback.set_callbacks(
                    order_callback=old_callbacks['order'],
                    trade_callback=old_callbacks['trade'],
                    error_callback=old_callbacks['error']
                )

            # 创建交易对象
            try:
                session_int = int(self._session_id) if self._session_id.isdigit() else hash(self._session_id) % 10000
                self.trader = xt_trader.XtQuantTrader(userdata_path, session_int, self.callback)
            except Exception as create_error:
                logger.error(f"创建交易对象失败：{str(create_error)}")
                return False

            # 启动交易
            self.trader.start()

            # 连接
            result = self.trader.connect()
            if result == 0:
                print("交易服务连接成功")
                return True
            else:
                logger.error(f"交易服务连接失败，错误码：{result}")
                return False

        except Exception as e:
            logger.error(f"连接交易服务失败：{str(e)}")
            return False

    def set_callbacks(self, order_callback=None, trade_callback=None, error_callback=None):
        """设置回调函数"""
        if self.callback:
            self.callback.set_callbacks(order_callback, trade_callback, error_callback)
            logger.info("✅ 设置回调成功")
        else:
            logger.error("⚠️ 回调对象未初始化")

    def add_account(self, account_id: str, account_type: str = 'STOCK') -> bool:
        """添加交易账户"""
        if not self.trader:
            logger.error("交易服务未连接")
            return False

        try:
            account = xt_type.StockAccount(account_id, account_type)
            if isinstance(account, str):
                logger.error(account)
                return False

            result = self.trader.subscribe(account)
            if result == 0:
                self.accounts[account_id] = account
                print(f"交易账户 {account_id} 添加成功")
                return True
            else:
                logger.error(f"订阅交易账户失败，错误码：{result}")
                return False

        except Exception as e:
            logger.error(f"添加交易账户失败：{str(e)}")
            return False

    def order_stock(self, account_id: str, stock_code: str, order_type: int,
                    volume: int, price_type: int, price: float = 0,
                    strategy_name: str = 'EasyXT', order_remark: str = '') -> int:
        """
        基础下单方法（直接调用xtquant）

        Args:
            account_id: 账户ID
            stock_code: 股票代码
            order_type: 订单类型（23买入/24卖出）
            volume: 数量
            price_type: 价格类型（11限价/5最新价/42上交所五档/47深交所五档等）
            price: 价格（限价单时使用）
            strategy_name: 策略名称
            order_remark: 订单备注

        Returns:
            int: 订单ID（>0成功，<=0失败）
        """
        if not self.trader or account_id not in self.accounts:
            logger.error("交易服务未连接或账户未添加")
            return -1

        account = self.accounts[account_id]

        try:
            order_id = self.trader.order_stock(
                account=account,
                stock_code=stock_code,
                order_type=order_type,
                order_volume=volume,
                price_type=price_type,
                price=price,
                strategy_name=strategy_name,
                order_remark=order_remark
            )

            if order_id > 0:
                logger.info(f"下单成功: {stock_code}, 数量: {volume}, 订单ID: {order_id}")
            else:
                logger.error(f"下单失败: {stock_code}, 数量: {volume}")

            return order_id

        except Exception as e:
            logger.error(f"下单操作失败：{str(e)}")
            return -1

    def sync_cancel_order(self, account_id: str, order_id: int) -> bool:
        """同步撤单"""
        if not self.trader or account_id not in self.accounts:
            logger.error("交易服务未连接或账户未添加")
            return False

        account = self.accounts[account_id]

        try:
            # 先检查委托状态
            orders = self.trader.query_stock_orders(account)
            if orders:
                for order in orders:
                    if order.order_id == order_id:
                        # 检查订单状态，如果已成交或已撤销，不能撤单
                        if hasattr(order, 'order_status'):
                            if order.order_status in [xt_const.ORDER_SUCCEEDED, xt_const.ORDER_CANCELED,
                                                      xt_const.ORDER_PART_CANCEL, xt_const.ORDER_JUNK]:
                                print(f"委托 {order_id} 已成交或已撤销，无法撤单")
                                return False

            # 尝试撤单
            result = self.trader.cancel_order_stock(account, order_id)
            if result == 0:
                print(f"同步撤单成功: {order_id}")
                return True
            else:
                print(f"同步撤单失败，错误码: {result}")
                return False

        except Exception as e:
            print(f"同步撤单操作失败: {str(e)}")
            return False

    def get_account_asset_detail(self, account_id: str) -> Optional[Dict[str, Any]]:
        """获取详细账户资产"""
        if not self.trader or account_id not in self.accounts:
            logger.error("交易服务未连接或账户未添加")
            return None

        account = self.accounts[account_id]

        try:
            asset = self.trader.query_stock_asset(account)
            if asset:
                return {
                    'account_id': asset.account_id,
                    'cash': asset.cash,
                    'frozen_cash': asset.frozen_cash,
                    'market_value': asset.market_value,
                    'total_asset': asset.total_asset,
                    'profit_loss': getattr(asset, 'profit_loss', 0.0),
                    'update_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            return None

        except Exception as e:
            logger.error(f"获取详细账户资产失败：{str(e)}")
            return None

    def get_positions_detail(self, account_id: str, code: str = None) -> pd.DataFrame:
        """获取详细持仓"""
        if not self.trader or account_id not in self.accounts:
            logger.error("交易服务未连接或账户未添加")
            return pd.DataFrame()

        account = self.accounts[account_id]

        try:
            if code:
                position = self.trader.query_stock_position(account, code)
                if position:
                    return pd.DataFrame([{
                        'code': position.stock_code,
                        'stock_name': getattr(position, 'stock_name', ''),
                        'volume': position.volume,
                        'can_use_volume': position.can_use_volume,
                        'open_price': position.open_price,
                        'market_value': position.market_value,
                        'frozen_volume': position.frozen_volume,
                        'profit_loss': getattr(position, 'profit_loss', 0.0),
                        'profit_loss_ratio': getattr(position, 'profit_loss_ratio', 0.0),
                        'update_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }])
                else:
                    return pd.DataFrame()
            else:
                positions = self.trader.query_stock_positions(account)
                if positions:
                    data = []
                    for pos in positions:
                        data.append({
                            'code': pos.stock_code,
                            'stock_name': getattr(pos, 'stock_name', ''),
                            'volume': pos.volume,
                            'can_use_volume': pos.can_use_volume,
                            'open_price': pos.open_price,
                            'market_value': pos.market_value,
                            'frozen_volume': pos.frozen_volume,
                            'profit_loss': getattr(pos, 'profit_loss', 0.0),
                            'profit_loss_ratio': getattr(pos, 'profit_loss_ratio', 0.0),
                            'update_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        })
                    return pd.DataFrame(data)
                else:
                    return pd.DataFrame()

        except Exception as e:
            logger.error(f"获取详细持仓信息失败：{str(e)}")
            return pd.DataFrame()

    def get_today_orders(self, account_id: str, cancelable_only: bool = False) -> pd.DataFrame:
        """获取当日委托"""
        if not self.trader or account_id not in self.accounts:
            logger.error("高级交易服务未连接或账户未添加")
            return pd.DataFrame()

        account = self.accounts[account_id]

        try:
            orders = self.trader.query_stock_orders(account, cancelable_only)
            if orders:
                data = []
                for order in orders:
                    order_type_name = '买入' if order.order_type == xt_const.STOCK_BUY else '卖出'

                    status_map = {
                        xt_const.ORDER_UNREPORTED: '未报',
                        xt_const.ORDER_WAIT_REPORTING: '待报',
                        xt_const.ORDER_REPORTED: '已报',
                        xt_const.ORDER_PART_SUCC: '部成',
                        xt_const.ORDER_SUCCEEDED: '已成',
                        xt_const.ORDER_PART_CANCEL: '部撤',
                        xt_const.ORDER_CANCELED: '已撤',
                        xt_const.ORDER_JUNK: '废单'
                    }
                    status_name = status_map.get(order.order_status, '未知')

                    data.append({
                        'order_id': order.order_id,
                        'stock_code': order.stock_code,
                        'order_type': order_type_name,
                        'order_volume': order.order_volume,
                        'order_price': order.price,
                        'traded_volume': order.traded_volume,
                        'order_status': status_name,
                        'order_time': order.order_time,
                        'order_remark': order.order_remark
                    })
                return pd.DataFrame(data)
            else:
                return pd.DataFrame()

        except Exception as e:
            logger.error(f"获取当日委托失败: {str(e)}")
            return pd.DataFrame()

    def query_stock_order(self, account_id: str, order_id: int):
        """
        查询单个订单

        Args:
            account_id: 账户ID
            order_id: 订单ID

        Returns:
            订单对象或None
        """
        if not self.trader or account_id not in self.accounts:
            return None

        account = self.accounts[account_id]

        try:
            return self.trader.query_stock_order(account, order_id)
        except Exception as e:
            logger.error(f"查询订单失败：{str(e)}")
            return None

    def disconnect(self):
        """断开连接"""
        if self.trader:
            try:
                self.trader.stop()
                print("交易服务已断开")
            except Exception as e:
                logger.error(f"断开交易服务失败: {str(e)}")
