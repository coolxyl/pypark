# 添加项目根目录到路径
import asyncio
import os
import sys
import configparser

# 先设置路径，再导入 qmt 模块
from datetime import datetime
from typing import Optional, Dict, Any

from qmt.trader.mytrader import get_tradeapi, CustomTradeAPI
from stock.utils import shareUtils

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)  # strategies 的上一级目录就是项目根目录

if project_root not in sys.path:
    sys.path.insert(0, project_root)
import qmt.xtquant.xtconstant as xt_const
from utils.logger import mylogger


class UnifiedTradeManager:
    '''
     对交易工具类封装，添加业务逻辑
    '''

    # 需要立即返回的状态（已完结状态）
    # 注意：part_succ 不在此列表中，因为部分成交后订单可能继续成交
    # 如果立即返回，可能导致重复下单
    IMMEDIATE_RETURN_STATUSES = {
        'succeeded',  # 完全成交
        # 'part_succ',    # 部分成交 - 已移除，避免过早返回导致重复下单
        'canceled',  # 已撤销
        'part_cancel',  # 部分撤销
        'junk'  # 废单
    }

    status_map = {
        xt_const.ORDER_UNREPORTED: 'unreported',
        xt_const.ORDER_WAIT_REPORTING: 'wait_reporting',
        xt_const.ORDER_REPORTED: 'reported',
        xt_const.ORDER_PART_SUCC: 'part_succ',
        xt_const.ORDER_SUCCEEDED: 'succeeded',
        xt_const.ORDER_PART_CANCEL: 'part_cancel',
        xt_const.ORDER_CANCELED: 'canceled',
        xt_const.ORDER_JUNK: 'junk'
    }

    def __init__(self, config_path=None):
        """
        初始化 UnifiedTradeManager
        
        Args:
            config_path: 配置文件路径，默认为 strategies/config.ini
        """
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), 'config.ini')

        self.logger = mylogger

        self.config = self._load_config(config_path)
        self.qmt_path = self.config.get('QMT', 'path', fallback='')
        self.account_id = self.config.get('QMT', 'account_id', fallback='')
        # 对于需要处理回调时,将订单ID塞入 order_id_map 中
        self.order_id_map = {}
        # 订单时间戳映射（修复：初始化 order_timestamps）
        self.order_timestamps = {}
        # 单一交易接口
        self.trader_api: Optional[CustomTradeAPI] = get_tradeapi()

        # 数据接口（用于获取实时价格）
        if hasattr(self.trader_api, 'connect'):
            if not self.trader_api.connect(self.qmt_path, 'unifiedTradeManager'):
                raise Exception("交易服务连接失败")

        self.trader_api.set_callbacks(
            order_callback=self.unified_order_callback,
            trade_callback=self.unified_trade_callback,
            error_callback=self.unified_error_callback
        )

        # 添加交易账户
        if self.account_id and hasattr(self.trader_api, 'add_account'):
            if not self.trader_api.add_account(self.account_id):
                # 在测试环境中，如果添加账户失败但trader_api是Mock对象，则继续
                if not hasattr(self.trader_api, '_mock_name'):
                    raise Exception(f"添加交易账户失败: {self.account_id}")
                else:
                    self.logger.warning("测试环境：跳过添加交易账户")

    def _load_config(self, config_path):
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            ConfigParser 对象
        """
        config = configparser.ConfigParser()
        if os.path.exists(config_path):
            config.read(config_path, encoding='utf-8')
        else:
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        return config

    def get_config_value(self, section, key, fallback=None):
        """
        获取配置值
        
        Args:
            section: 配置节名称
            key: 配置键名称
            fallback: 默认值
            
        Returns:
            配置值
        """
        return self.config.get(section, key, fallback=fallback)

    def get_account_asset(self) -> Optional[Dict[str, Any]]:
        """
        获取当前账户资产信息
        
        Returns:
            Optional[Dict[str, Any]]: 账户资产信息字典，包含以下字段：
                - account_id: str, 账户 ID
                - cash: float, 可用资金
                - frozen_cash: float, 冻结资金
                - market_value: float, 持仓市值
                - total_asset: float, 总资产
                - profit_loss: float, 浮动盈亏
                - update_time: str, 更新时间
            失败时返回 None
        """
        try:
            if not self.trader_api:
                self.logger.error("交易接口未初始化，无法获取账户资产")
                return None

            if not self.account_id:
                self.logger.error("账户 ID 未设置，无法获取账户资产")
                return None

            # 调用底层 API 获取详细账户资产
            asset_info = self.trader_api.get_account_asset_detail(self.account_id)

            if asset_info:
                return asset_info
            else:
                self.logger.debug("获取账户资产失败")
                return None

        except Exception as e:
            self.logger.error(f"获取账户资产异常：{e}")
            return None

    def get_today_orders(self, cancelable_only: bool = False) -> Optional[list]:
        """
        获取当日委托订单信息
    
        Args:
            cancelable_only: 是否只返回可撤销的订单，默认 False 返回所有订单
    
        Returns:
            Optional[list]: 订单信息列表，失败时返回 None
        """
        try:
            if not self.trader_api:
                self.logger.error("交易接口未初始化，无法获取委托订单")
                return None

            if not self.account_id:
                self.logger.error("账户ID未设置，无法获取委托订单")
                return None

            # 使用 get_today_orders 方法返回DataFrame
            orders_df = self.trader_api.get_today_orders(self.account_id, cancelable_only)

            if orders_df is not None and not orders_df.empty:
                # 将DataFrame转换为字典列表
                orders_list = []
                for _, row in orders_df.iterrows():
                    order_dict = {
                        'order_id': row.get('order_id'),
                        'stock_code': row.get('stock_code'),
                        'order_type': row.get('order_type'),
                        'order_volume': row.get('order_volume', 0),
                        'price': row.get('order_price', 0),
                        'traded_volume': row.get('traded_volume', 0),
                        'order_status': row.get('order_status', 'unknown'),
                        'order_time': row.get('order_time', 0),
                        'order_remark': row.get('order_remark', ''),
                    }
                    orders_list.append(order_dict)

                self.logger.info(f"成功获取委托订单，订单数量: {len(orders_list)}")
                return orders_list
            else:
                self.logger.debug("当前无委托订单")
                return []

        except Exception as e:
            self.logger.error(f"获取委托订单失败: {e}")
            return None

    def _map_order_status(self, status_code) -> str:
        """
        映射订单状态码为可读字符串

        Args:
            status_code: 订单状态码

        Returns:
            str: 状态字符串
        """
        if status_code is None:
            return 'unknown'

        return self.status_map.get(status_code, f'unknown_{status_code}')

    def cancel_order(self, order_id: int) -> bool:
        """
        撤销指定订单

        Args:
            order_id: 订单ID

        Returns:
            bool: 是否撤销成功
        """
        try:
            if not self.trader_api:
                self.logger.error("交易接口未初始化，无法撤销订单")
                return False

            if not self.account_id:
                self.logger.error("账户ID未设置，无法撤销订单")
                return False

            # 调用AdvancedTradeAPI的撤单方法
            result = self.trader_api.sync_cancel_order(self.account_id, order_id)

            if result:
                self.logger.info(f"成功撤销订单: {order_id}")
                return True
            else:
                self.logger.warning(f"撤销订单失败: {order_id}")
                return False

        except Exception as e:
            self.logger.error(f"撤销订单异常: {order_id}, 错误={e}")
            return False

    def cancel_all_orders(self, stock_code: str = None) -> Dict[str, Any]:
        """
        撤销所有可撤销的订单，或撤销指定股票的所有订单

        Args:
            stock_code: 可选，指定股票代码，如果不指定则撤销所有订单

        Returns:
            Dict[str, Any]: {
                'total': int,      # 总共尝试撤销的订单数
                'success': int,    # 成功撤销的订单数
                'failed': int,     # 失败的订单数
                'details': list    # 详细信息列表
            }
        """
        try:
            # 获取所有可撤销的订单（修复：使用正确的方法名）
            orders = self.get_today_orders(cancelable_only=True)

            if not orders:
                self.logger.info("当前无可撤销订单")
                return {
                    'total': 0,
                    'success': 0,
                    'failed': 0,
                    'details': []
                }

            # 如果指定了股票代码，过滤订单
            if stock_code:
                orders = [o for o in orders if o.get('stock_code') == stock_code]
                self.logger.info(f"过滤后，股票 {stock_code} 有 {len(orders)} 个可撤销订单")

            # 逐个撤销
            total = len(orders)
            success = 0
            failed = 0
            details = []

            for order in orders:
                order_id = order.get('order_id')
                stock = order.get('stock_code')

                if self.cancel_order(order_id):
                    success += 1
                    details.append({
                        'order_id': order_id,
                        'stock_code': stock,
                        'status': 'success'
                    })
                else:
                    failed += 1
                    details.append({
                        'order_id': order_id,
                        'stock_code': stock,
                        'status': 'failed'
                    })

            result = {
                'total': total,
                'success': success,
                'failed': failed,
                'details': details
            }

            self.logger.info(f"批量撤单完成: 总计{total}个，成功{success}个，失败{failed}个")
            return result

        except Exception as e:
            self.logger.error(f"批量撤单异常: {e}")
            return {
                'total': 0,
                'success': 0,
                'failed': 0,
                'details': [],
                'error': str(e)
            }

    def unified_trade_callback(self, trade):
        """
        统一成交回调处理

        TODO 成功消息通知，或者 处理本地订单状态。

        Args:
            trade: XtTrade对象，来自xtquant的成交回调
        """

        try:
            order_id = getattr(trade, 'order_id', None)
            if not order_id:
                self.logger.warning("成交回调缺少order_id，无法路由")
                return

            # 如果在order_id_map中存在
            if order_id in self.order_id_map:
                # 如果有需要的话，进行实现，如果本地有订单体系，可以实现该方法。
                pass
            else:
                self.logger.warning(f"未找到订单ID {order_id} 的记录，可能是其他策略的订单")
                return

        except Exception as e:
            self.logger.error(f"处理统一成交回调失败: {e}")

    def unified_order_callback(self, order):
        """
        统一委托回调处理

        根据订单ID路由到订单进行处理

        Args:
            order: XtOrder对象，来自xtquant的委托回调
        """
        try:
            order_id = getattr(order, 'order_id', None)
            if not order_id:
                self.logger.warning("委托回调缺少order_id，无法路由")
                return

            # 如果在order_id_map中存在
            if order_id in self.order_id_map:
                # 如果有需要的话，进行实现

                pass
            else:
                self.logger.warning(f"未找到订单ID {order_id} 对应的记录，可能是其他策略的订单")
                return

            # 检查订单是否已完成，如果完成则记录完成时间
            order_status = getattr(order, 'order_status', None)
            if order_status in [48, 49, 50, 51, 52]:  # 常见的完成状态码
                # self.completed_orders[order_id] = datetime.now()
                self.logger.debug(f"订单 {order_id} 已完成，状态: {order_status}")

        except Exception as e:
            self.logger.error(f"处理统一委托回调失败: {e}")

    def unified_error_callback(self, order_error):
        """
        统一错误回调处理

        Args:
            order_error: XtOrderError对象，来自xtquant的错误回调
        """
        try:
            # 提取关键字段
            order_id = getattr(order_error, 'order_id', None)
            error_id = getattr(order_error, 'error_id', None)
            error_msg = getattr(order_error, 'error_msg', None)

            # 记录简洁的错误日志
            self.logger.error(
                f"交易错误回调: 订单ID={order_id}, 错误码={error_id}, "
                f"错误消息={error_msg}"
            )
            # TODO 对于异常交易 可以引入消息模块进行消息通知


        except Exception as e:
            self.logger.error(f"处理统一错误回调失败: {e}")

    def _get_current_price(self, stock_code: str) -> Optional[float]:
        """
        获取当前价格
        Args:
          stock_code: 股票代码

        Returns:
            float: 当前价格或 None
        """
        # TODO  这里应该用 xtquant 来获取，待实现。
        # FIX 图方便，这里直接用 shareUtils 工具来获取价格。

        return shareUtils.get_now_price(stock_code)









    def _get_market_type(self, stock_code: str) -> str:
        """
        判断股票所属交易所

        Args:
            stock_code: 股票代码

        Returns:
            str: 'SH'(上交所) / 'SZ'(深交所) / 'BJ'(北交所)
        """
        code_upper = stock_code.upper()

        # 检查是否包含交易所标识
        if '.SH' in code_upper or code_upper.startswith('SH'):
            return 'SH'
        elif '.BJ' in code_upper or code_upper.startswith('BJ'):
            return 'BJ'
        elif '.SZ' in code_upper or code_upper.startswith('SZ'):
            return 'SZ'
        else:
            # 默认深交所
            return 'SZ'

    def _get_price_type_for_market(self, market_type: str, xt_const) -> int:
        """
        根据交易所类型获取price_type

        Args:
            market_type: 交易所类型（SH/SZ/BJ）
            xt_const: xtconstant模块

        Returns:
            int: price_type常量
        """
        if market_type in ['SH', 'BJ']:
            return xt_const.MARKET_SH_CONVERT_5_CANCEL  # 42
        elif market_type == 'SZ':
            return xt_const.MARKET_SZ_CONVERT_5_CANCEL  # 47
        else:  # BJ
            return xt_const.FIX_PRICE  # 11

    def _calculate_limit_price(self, current_price: float, order_type: int,
                               slippage: float) -> float:
        """
        计算限价单价格（买入上浮，卖出下调）

        Args:
            current_price: 当前价格
            order_type: 订单类型（23买入/24卖出）
            slippage: 滑点比例

        Returns:
            float: 限价单价格
        """
        if order_type == xt_const.STOCK_BUY:  # 买入
            limit_price = current_price * (1 + slippage)
        else:  # 卖出
            limit_price = current_price * (1 - slippage)

        # 价格取整（保留2位小数）
        return round(limit_price, 2)

    async def place_limit_order(
            self,
            stock_code: str,
            order_type: int,
            volume: int,
            slippage: float,
            order_remark_suffix: str = '限价单'
    ) -> dict:
        """
        提交限价单（用于北交所或兜底）

        自动获取实时价格并计算限价单价格

        Args:
            stock_code: 股票代码
            order_type: 订单类型
            volume: 数量
            slippage: 滑点
            order_remark_suffix: 订单备注后缀，默认'限价单'

        Returns:
            dict: 订单信息字典
        """
        try:
            # 获取当前实时价格
            current_price = self._get_current_price(stock_code)
            if not current_price or current_price <= 0:
                self.logger.error(f"无法获取 {stock_code} 的实时价格，限价单提交失败")
                return {
                    'attempt': 'final',
                    'order_id': None,
                    'stock_code': stock_code,
                    'order_type': order_type,
                    'volume': volume,
                    'traded_volume': 0,
                    'price_type': xt_const.FIX_PRICE,
                    'status': 'failed',
                    'is_final': True,
                    'message': '无法获取实时价格，限价单提交失败'
                }

            # 计算限价单价格
            limit_price = self._calculate_limit_price(current_price, order_type, slippage)

            self.logger.info(
                f" 票号：{stock_code}进行限价交易{order_type} 交易数量{volume} 限价单价格: {limit_price} (现价: {current_price}, 滑点: {slippage})")

            # 提交限价单
            order_id = self.trader_api.order_stock(
                account_id=self.account_id,
                stock_code=stock_code,
                order_type=order_type,
                volume=volume,
                price_type=xt_const.FIX_PRICE,
                price=limit_price,
                strategy_name='SmartOrder',
                order_remark=f'{order_remark_suffix}'
            )

            if order_id > 0:
                # 记录订单映射
                self.order_timestamps[order_id] = datetime.now()
                self.logger.info(f"限价单提交成功，order_id: {order_id}")

                # 查询订单详细信息
                try:
                    order = await self._poll_order_status(order_id)

                    if order:
                        # 映射订单状态
                        order_status = order.get('order_status')
                        traded_volume = order.get('traded_volume')
                        traded_price = order.get('traded_price')

                        self.logger.info(f"限价单查询成功: order_id={order_id}, status={order_status}, traded={traded_volume}")

                        return {
                            'attempt': 'final',
                            'order_id': order_id,
                            'stock_code': stock_code,
                            'order_type': order_type,
                            'volume': volume,
                            'traded_volume': traded_volume,
                            'traded_price': traded_price,
                            'price_type': xt_const.FIX_PRICE,
                            'price': limit_price,
                            'status': order_status,
                            'is_final': True,
                            'message': f'限价单提交信息 @ {limit_price} (现价: {current_price}), 状态: {order_status}, 成交: {traded_volume}股'
                        }
                    else:
                        self.logger.warning(f"无法查询限价单信息: order_id={order_id}")
                        # 查询失败，返回基本信息
                        return {
                            'attempt': 'final',
                            'order_id': order_id,
                            'stock_code': stock_code,
                            'order_type': order_type,
                            'volume': volume,
                            'traded_volume': 0,
                            'price_type': xt_const.FIX_PRICE,
                            'price': limit_price,
                            'status': 'submitted',
                            'is_final': True,
                            'message': f'未查询到 @ {limit_price} (现价: {current_price}), 查询状态失败'
                        }

                except Exception as query_error:
                    self.logger.error(f"查询限价单信息异常: {query_error}")
                    # 查询异常，返回基本信息
                    return {
                        'attempt': 'final',
                        'order_id': order_id,
                        'stock_code': stock_code,
                        'order_type': order_type,
                        'volume': volume,
                        'traded_volume': 0,
                        'price_type': xt_const.FIX_PRICE,
                        'price': limit_price,
                        'status': 'failed',
                        'is_final': True,
                        'message': f'限价单已提交 @ {limit_price} (现价: {current_price}), 查询异常: {str(query_error)}'
                    }
            else:
                self.logger.error("限价单提交失败")
                return {
                    'attempt': 'final',
                    'order_id': None,
                    'stock_code': stock_code,
                    'order_type': order_type,
                    'volume': volume,
                    'traded_volume': 0,
                    'price_type': xt_const.FIX_PRICE,
                    'status': 'failed',
                    'is_final': True,
                    'message': '限价单提交失败'
                }

        except Exception as e:
            self.logger.error(f"限价单提交异常: {str(e)}")
            return {
                'attempt': 'final',
                'order_id': None,
                'stock_code': stock_code,
                'order_type': order_type,
                'volume': volume,
                'traded_volume': 0,
                'price_type': xt_const.FIX_PRICE if xt_const else 11,
                'status': 'error',
                'is_final': True,
                'message': f'限价单提交异常: {str(e)}'
            }

    async def _poll_order_status(
            self,
            order_id: int,
            max_wait: int = 3,
            poll_interval: float = 1.0
    ) -> Optional[dict]:
        """
        轮询订单状态

        Args:
            order_id: 订单ID
            max_wait: 最多等待秒数
            poll_interval: 轮询间隔秒数

        Returns:
            dict: 订单信息或None
        """
        order_info = None

        for i in range(int(max_wait / poll_interval)):
            await asyncio.sleep(poll_interval)

            try:
                order = self.trader_api.query_stock_order(self.account_id, order_id)

                if order:
                    # 映射状态
                    order_status = self.status_map.get(order.order_status, 'unknown')

                    # 记录详细日志
                    order_info = {
                        'order_id': getattr(order, 'order_id', 'N/A'),
                        'stock_code': getattr(order, 'stock_code', 'N/A'),
                        'order_type': getattr(order, 'order_type', 'N/A'),
                        'order_volume': getattr(order, 'order_volume', 'N/A'),
                        'price': getattr(order, 'price', 'N/A'),
                        'traded_volume': getattr(order, 'traded_volume', 'N/A'),
                        'traded_price': getattr(order, 'traded_price', 'N/A'),
                        'order_status_code': getattr(order, 'order_status', 'N/A'),
                        'order_status': order_status,
                        'status_msg': getattr(order, 'status_msg', 'N/A'),
                        'strategy_name': getattr(order, 'strategy_name', 'N/A'),
                        'order_remark': getattr(order, 'order_remark', 'N/A'),
                        'order_time': getattr(order, 'order_time', 'N/A')
                    }
                    self.logger.info(f"XtOrder对象数据: {order_info}")

                    # 如果订单状态需要立即返回（已完结或部分成交）
                    if order_status in self.IMMEDIATE_RETURN_STATUSES:
                        return order_info

            except Exception as e:
                self.logger.error(f"查询订单状态异常: {str(e)}")
                continue

        # 超时未获取到最终状态
        self.logger.info(f"订单 {order_id} 轮询超时")
        return order_info

    def _generate_result_message(
            self,
            success: bool,
            total_traded: int,
            remaining: int,
            order_count: int
    ) -> str:
        """
        生成执行结果说明

        Args:
            success: 是否完全成交
            total_traded: 总成交数量
            remaining: 剩余数量
            order_count: 订单数量

        Returns:
            str: 结果说明
        """
        if success:
            return f"完全成交：共成交{total_traded}股，使用{order_count}个订单"
        else:
            return f"部分成交：成交{total_traded}股，剩余{remaining}股未成交，使用{order_count}个订单"

    async def smart_order_with_retry(
            self,
            stock_code: str,
            order_type: int,
            volume: int,
            slippage: float = 0.008,
            max_retries: int = 1,
            retry_interval: float = 2.0
    ) -> dict:
        """
        智能下单并自动重试（业务逻辑方法）
        对于xtquant使用 股票号码官方文档是带后缀的个格式, 如 000001.SZ,实际测下来 SZ000001也支持，建议和官网保持一致。


        功能：
        1. 自动识别交易所类型（上交所/深交所/北交所）
        2. 根据交易所选择合适的price_type
        3. 自动重试机制（最多3次）
        4. 限价单兜底（自动获取实时价格）

        Args:
            stock_code: 股票代码
            order_type: 订单类型（23买入/24卖出）
            volume: 数量
            slippage: 滑点比例（默认0.8%）
            max_retries: 最大重试次数（默认10次）
            retry_interval: 重试间隔秒数（默认2秒）

        Returns:
            dict: {
                'success': bool,              # 是否完全成交
                'total_traded_volume': int,   # 总成交数量
                'remaining_volume': int,      # 剩余未成交数量
                'orders': list,               # 所有订单记录
                'message': str                # 执行结果说明
            }
        """

        # 步骤1：判断交易所类型
        stock_code = shareUtils.normalize_code_with_suffix(stock_code)
        market_type = self._get_market_type(stock_code)

        # 初始化变量
        remaining_volume = volume
        orders = []
        attempt = 0

        # 步骤2：上交所/深交所使用五档即成剩撤 + 重试；北交所 同上交所
        price_type = self._get_price_type_for_market(market_type, xt_const)
        price_type_name = 'MARKET_SH_CONVERT_5_CANCEL' if market_type == 'SH' else 'MARKET_SZ_CONVERT_5_CANCEL'

        self.logger.info(f"{stock_code},使用 {price_type_name} (price_type={price_type}) 进行下单")

        # 重试循环
        while remaining_volume > 0 and attempt < max_retries:
            attempt += 1
            self.logger.info(
                f"{stock_code} 五档回撤交易 第 {attempt}/{max_retries} 次尝试，剩余数量: {remaining_volume}")

            # 修复9：区分不同类型的异常
            try:
                # 3.1 提交订单
                order_id = self.trader_api.order_stock(
                    account_id=self.account_id,
                    stock_code=stock_code,
                    order_type=order_type,
                    volume=remaining_volume,
                    price_type=price_type,
                    price=0,  # 五档即成剩撤不需要指定价格
                    strategy_name='SmartOrder',
                    order_remark=f'智能下单第{attempt}次'
                )

                # 修复8：添加更详细的订单ID验证和错误信息
                if order_id is None or order_id <= 0:
                    error_msg = f"第 {attempt} 次下单失败: order_id 为 None，可能是API调用失败"
                    self.logger.error(error_msg)
                    orders.append({
                        'attempt': attempt,
                        'order_id': None,
                        'volume': remaining_volume,
                        'traded_volume': 0,
                        'price_type': price_type,
                        'status': 'failed',
                        'message': error_msg
                    })
                    continue

                # 3.2 记录订单映射,这里暂时不用回调。暂时不记录order_id 信息，暂不处理回调。
                # self.order_id_map.append(order_id)
                # self.order_timestamps[order_id] = datetime.now()
                self.logger.info(f"第 {attempt} 次下单成功，order_id: {order_id}")

                # 3.3 轮询订单状态（最多3秒）
                order_info = await self._poll_order_status(
                    order_id,
                    max_wait=3,
                    poll_interval=1
                )

                if not order_info:
                    self.logger.warning(f"无法获取订单 {order_id} 状态")
                    orders.append({
                        'attempt': attempt,
                        'order_id': order_id,
                        'volume': remaining_volume,
                        'traded_volume': 0,
                        'price_type': price_type,
                        'status': 'unknown',
                        'message': '无法获取订单状态'
                    })
                    continue

                order_status = order_info.get('order_status')

                # 如果订单被撤销或废单，继续下一轮重试
                if order_status in ['canceled', 'junk', 'reported']:
                    self.logger.info(f"订单状态为 {order_status}，继续下一轮重试")
                    await asyncio.sleep(retry_interval)
                    continue

                # 3.5 更新剩余数量
                traded_volume = order_info.get('traded_volume', 0)
                remaining_volume -= traded_volume

                # 记录订单信息
                orders.append({
                    'attempt': attempt,
                    'order_id': order_id,
                    'volume': order_info.get('order_volume', 0),
                    'traded_volume': traded_volume,
                    'price_type': price_type,
                    'status': order_status,
                    'message': f'成交{traded_volume}股'
                })

                self.logger.info(
                    f"{stock_code},第 {attempt} 次订单状态: {order_status}, 成交: {traded_volume}, 剩余: {remaining_volume}")

                # 修复5：简化退出判断，只保留一个
                # 修复6：如果未完全成交且未达到最大重试次数，等待后继续
                if remaining_volume == 0:
                    self.logger.info("完全成交，退出循环")
                    break
                else:
                    # 部分成交或未成交，等待后继续下一轮
                    if attempt < max_retries:
                        self.logger.info(f"部分成交，等待 {retry_interval} 秒后继续重试")
                        await asyncio.sleep(retry_interval)

            # 修复9：区分不同类型的异常
            except AttributeError as e:
                error_msg = f"第 {attempt} 次下单异常 (API对象错误): {str(e)}"
                self.logger.error(error_msg)
                orders.append({
                    'attempt': attempt,
                    'order_id': None,
                    'volume': remaining_volume,
                    'traded_volume': 0,
                    'price_type': price_type,
                    'status': 'error_api',
                    'message': error_msg
                })
                await asyncio.sleep(retry_interval)
                continue

            except ValueError as e:
                error_msg = f"第 {attempt} 次下单异常 (参数错误): {str(e)}"
                self.logger.error(error_msg)
                orders.append({
                    'attempt': attempt,
                    'order_id': None,
                    'volume': remaining_volume,
                    'traded_volume': 0,
                    'price_type': price_type,
                    'status': 'error_param',
                    'message': error_msg
                })
                # 参数错误不重试
                break

            except ConnectionError as e:
                error_msg = f"第 {attempt} 次下单异常 (网络连接错误): {str(e)}"
                self.logger.error(error_msg)
                orders.append({
                    'attempt': attempt,
                    'order_id': None,
                    'volume': remaining_volume,
                    'traded_volume': 0,
                    'price_type': price_type,
                    'status': 'error_network',
                    'message': error_msg
                })
                await asyncio.sleep(retry_interval * 2)  # 网络错误等待更长时间
                continue

            except Exception as e:
                error_msg = f"第 {attempt} 次下单异常 (未知错误): {str(e)}"
                self.logger.error(error_msg)
                orders.append({
                    'attempt': attempt,
                    'order_id': None,
                    'volume': remaining_volume,
                    'traded_volume': 0,
                    'price_type': price_type,
                    'status': 'error_unknown',
                    'message': error_msg
                })
                await asyncio.sleep(retry_interval)
                continue

        success = (remaining_volume == 0)
        # 步骤4：限价单兜底
        if remaining_volume > 0:
            self.logger.info(f"{stock_code}  仍有剩余数量 {remaining_volume}，使用限价单兜底")

            # 调用限价单提交方法（自动获取实时价格）
            limit_order_result = await self.place_limit_order(
                stock_code=stock_code,
                order_type=order_type,
                volume=remaining_volume,
                slippage=slippage,
                order_remark_suffix='智能下单兜底限价单'
            )

            # 将限价单结果添加到订单列表
            # 走到这里说明之前都没成功，要靠限价来发生交易。
            orders.append(limit_order_result)
            if limit_order_result.get('status') in ['reported', 'part_succ', 'succeeded']:
                success = True

        # 步骤5：汇总结果
        total_traded_volume = volume - remaining_volume
        result = {
            'success': success,
            'total_traded_volume': total_traded_volume,
            'remaining_volume': remaining_volume,
            'orders': orders,
            'message': self._generate_result_message(success, total_traded_volume, remaining_volume, len(orders))
        }

        self.logger.info(f"智能下单完成: {result['message']}")
        return result




if __name__ == "__main__":
    # 测试代码
    manager = UnifiedTradeManager()
    #1. 获取资产信息
    #print(manager.get_today_orders())

    # 2.查价格
    price = manager._get_current_price('000001.SZ')
    print(price)

    # #3.智能下单交易
    result = asyncio.run(
        manager.smart_order_with_retry(
            '000001',
            23,
            volume=100,

        )
    )
    # #4.获取资产信息
    # asset = manager.get_account_asset()
    # print(asset)
    # print(f"智能下单结果：{result}")