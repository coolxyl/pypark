# 使用示例
import MyTT
import shareUtils



if __name__ == '__main__':
    # 一只股票的K线数据
    df = shareUtils.get_price_from_sina('sz000001',frequency='1d',count=50)

    # 根据K 线数据，计算指标
    # # 5 日均线
    print(MyTT.MA(df['close'],5))
    # 10 日均线
    print(MyTT.MA(df['close'],10))
    #macd 指标
    print(MyTT.MACD(df['close']))

    codes = shareUtils.get_all_codes()
    #N 只股票的实时价格
    # shareUtils.quotation.real(codes)

    #codesqutation = shareUtils.quotation.real(['SZ000001'])

    #print(codesqutation)

    price = shareUtils.get_now_price('sz000001')
    print(price)

