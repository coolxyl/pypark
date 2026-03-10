import json, requests, datetime
import pandas as pd
import easyquotation
import easyquotation.helpers as easyhelpers
import akshare
import re

quotation = easyquotation.use('sina')  # 新浪 ['sina'] 腾讯 ['tencent', 'qq']


def get_all_codes():
    """
    获取所有股票代码列表
    
    Returns:
        list: 标准化后的股票代码列表（包含市场前缀）
    """
    stock_codes = quotation.load_stock_codes()

    # 使用集合推导式去重并格式化股票代码
    unique_codes = {
        easyhelpers.get_stock_type(code) + code[-6:]
        for code in stock_codes
        if code and len(code) >= 6
    }

    return list(unique_codes)


def normalize_code_with_prefix(code):
    """
    将股票代码标准化为带小写前缀的格式（如 sz000001）
    
    Args:
        code: 股票代码，支持多种格式：
              - '000001' (纯 6 位代码)
              - '000001.SZ' (带后缀格式)
              - 'sz000001' (带前缀格式)
              - 'SZ000001' (大写前缀格式)
        
    Returns:
        str: 标准化后的股票代码格式（小写前缀 + 代码）
        
    Examples:
        >>> normalize_code_with_prefix('000001')
        'sz000001'
        >>> normalize_code_with_prefix('000001.SZ')
        'sz000001'
        >>> normalize_code_with_prefix('SZ000001')
        'sz000001'
        >>> normalize_code_with_prefix('sh600366')
        'sh600366'
        >>> normalize_code_with_prefix('bj830001')
        'bj830001'
    """
    # 先转为大写并去除空白，方便统一处理
    code = code.upper().strip()
    
    # 使用正则提取 6 位数字代码部分
    match = re.search(r'(\d{6})', code)
    if match:
        code_6digit = match.group(1)
    else:
        # 如果没有找到 6 位数字，返回原代码
        return code.lower()
    
    # 根据代码获取市场前缀
    market_prefix = easyhelpers.get_stock_type(code_6digit)
    
    # 返回小写前缀 + 6 位代码的格式
    return f"{market_prefix}{code_6digit}"


def get_code_without_prefix(code):
    """
    去除股票代码的前缀（sz/sh/bj 等）
    
    Args:
        code: 股票代码，可以是带前缀或不带前缀的格式
        
    Returns:
        str: 去除前缀后的 6 位股票代码
        
    Examples:
        >>> 'sz000001'
        '000001'
        >>> 'sh600366'
        '600366'
        >>> 'bj830001'
        '830001'
        >>> '000001'
        '000001'
    """
    # 使用正则提取 6 位数字代码部分
    match = re.search(r'(\d{6})', code)
    if match:
        code_6digit = match.group(1)
        return code_6digit
    else:
        # 表示未找到6位订单号
        return code


def normalize_code_with_suffix(code):
    """
    将股票代码标准化为带市场后缀的格式（如 000001.SZ）
    
    Args:
        code: 股票代码，支持多种格式：
              - '000001' (纯 6 位代码)
              - '000001.SZ' (已标准化格式)
              - 'sz000001' (带前缀格式)
              - 'SZ000001' (大写前缀格式)
        
    Returns:
        str: 标准化后的股票代码格式（代码。市场）
        
    Examples:
         '000001' ->'000001.SZ'
        '000001.SZ' ->'000001.SZ'
        'sz000001' -> '000001.SZ'
    """
    # 先去除可能的前缀和已有的后缀
    code = code.upper().strip()
    
    # 使用正则提取 6 位数字代码部分
    match = re.search(r'(\d{6})', code)
    if match:
        code_6digit = match.group(1)
    else:
        # 如果没有找到 6 位数字，返回原代码
        return code
    
    # 根据代码前缀判断市场
    market_prefix = easyhelpers.get_stock_type(code_6digit)
    
    # 转换为标准格式（如 SZ -> .SZ）
    market_suffix = '.' + market_prefix.upper()
    
    return f"{code_6digit}{market_suffix}"



def get_now_price(code):
    '''
    支持传入 0000001，sz000001，SZ000001
    :param code:
    :return:
    '''
    code_quotation = quotation.real(normalize_code_with_prefix(code))
    simple_code = get_code_without_prefix(code)
    return code_quotation[simple_code]['now']

# DEPRECATED  可以直接使用 akshare.stock_zh_a_minute
# 新浪全周期获取函数
# 支持 5m,15m,30m,60m  日线1d=240m   周线1w=1200m  1月=7200m
# sh,sz
def get_price_from_sina(code, count=10, frequency='60m', end_date=''):
    # 频率转换和数据条数保存
    frequency = frequency.replace('1d', '240m').replace('1w', '1200m').replace('1M', '7200m')
    mcount = count

    # 解析 K 线周期数
    ts = int(frequency[:-1]) if frequency[:-1].isdigit() else 1

    # 处理带结束时间的情况（仅适用于日线、周线、月线）
    has_end_date = (end_date != '') and (frequency in ['240m', '1200m', '7200m'])

    if has_end_date:
        end_date = pd.to_datetime(end_date) if not isinstance(end_date, datetime.date) else end_date
        # 以下逻辑已废弃，使用保守估计策略
        # unit=1
        # if frequency == '1200m':
        #     unit = 5
        # elif frequency == '7200m':
        #     unit = 30

        # 使用防御性编程策略：周线除以 4（而非 5），月线除以 29（而非 30）
        unit = 4 if frequency == '1200m' else 29 if frequency == '7200m' else 1
        count = count + (datetime.datetime.now() - end_date).days // unit

    # 构建请求 URL
    URL = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale={ts}&ma=5&datalen={count}'

    # 获取数据
    dstr = json.loads(requests.get(URL).content)

    # 转换为 DataFrame
    df = pd.DataFrame(dstr, columns=['day', 'open', 'high', 'low', 'close', 'volume'])

    # 转换数据类型
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)

    # 处理索引
    df.day = pd.to_datetime(df.day)
    df.set_index(['day'], inplace=True)
    df.index.name = ''

    # 日线带结束时间先返回
    if has_end_date:
        return df[df.index <= end_date][-mcount:]

    return df


def get_daily_history_by_source(code: str,
                                start_date: str = "20200101", end_date: str = "20231231",
                                adjust: str = "qfq", source: str = "qq") -> pd.DataFrame:
        """
        根据指定数据源获取股票历史行情数据

        Args:
            stock_code (str): 股票代码
            start_date (str): 开始日期，格式 YYYYMMDD
            end_date (str): 结束日期，格式 YYYYMMDD
            adjust (str): 复权类型 ("qfq": 前复权, "hfq": 后复权, "": 不复权)
            source (str): 数据源标识 ["em"|"qq"|"sina"]

        Returns:
            pd.DataFrame: 股票历史行情数据
        """
        try:
            temp_code = normalize_code_with_prefix(code)
            if source == "em":  # 东方财富 已废弃
                stock_hist = akshare.stock_zh_a_hist(
                    symbol=temp_code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust
                )
                column_mapping = {
                    "日期": "trade_date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "turnover",
                    "振幅": "amplitude",
                    "涨跌幅": "change_percent",
                    "涨跌额": "change_amount",
                    "换手率": "turnover_rate",
                    "股票代码": "code"
                }
                if not stock_hist.empty:
                    stock_hist.rename(columns=column_mapping, inplace=True)
            elif source == "qq":  # 腾讯证券
                # 腾讯需要加上前缀
                stock_hist = akshare.stock_zh_a_hist_tx(
                    symbol=temp_code,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust
                )
                column_mapping = {"date": "trade_date", "open": "open", "close": "close", "high": "high", "low": "low",
                                  "amount": "volume"}

                if not stock_hist.empty:
                    stock_hist.rename(columns=column_mapping, inplace=True)
            elif source == "sina":  # 新浪财经
                #新浪也需要加上前缀
                stock_hist = akshare.stock_zh_a_daily(
                    symbol=temp_code,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust
                )
                column_mapping ={
                    "date": "trade_date",
                    "open": "open",
                    "high" : "high",
                    "low" : "low",
                    "close" : "close",
                    "volume" : "volume",
                    "amount" : "turnover",
                    "outstanding_share": "outstanding_share",
                    "turnover" : "turnover"
                }
                if not stock_hist.empty:
                    stock_hist.rename(columns=column_mapping, inplace=True)

            else:
                raise ValueError(f"不支持的数据源: {source}")

            if not stock_hist.empty:
                return stock_hist
            else:
                raise Exception("获取的数据为空")

        except Exception as e:

            return pd.DataFrame()





if __name__ == '__main__':
    # df = get_price_from_sina('sz000001', frequency='5m', count=10)
    # print(df)
    stock_codes = quotation.load_stock_codes()

    codes = get_all_codes()
    print(codes)
    df = quotation.get_stock_data(['sh600366'])
    print(df)
    df = quotation.get_stock_data(['sz000001'])
    print(df)

    #df = akshare.stock_zh_a_hist_min_em('sh600366', '2026-01-04 09:00:00', '2026-01-05 09:00:00', '5')
    print(df)
    df = get_daily_history_by_source('SH600366', '2026-01-04', '2026-01-08', 'qfq', 'qq')
    print(df)

    df = akshare.stock_zh_a_minute('600366.SH', '1')
    print(df)

