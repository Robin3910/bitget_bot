import bitget.v1.mix.order_api as maxOrderApi
import bitget.bitget_api as baseApi
import bitget.consts as bg_constants

from bitget.exceptions import BitgetAPIException

if __name__ == '__main__':
    apiKey = "bg_0fcc6babcd593ec94288b99a7445e196"
    secretKey = "8e715cf50188997531fa00c9e607f201a70e394b920e1986163e6e453475d10c"
    passphrase = "robin3910"
    baseApi = baseApi.BitgetApi(apiKey, secretKey, passphrase)

    # Demo 设置保证金
    # try:
    #     params = {}
    #     params["symbol"] = "SBTCSUSDT"
    #     params["marginCoin"] = "SUSDT"
    #     params["marginMode"] = "crossed"
    #     params["productType"] = "susdt-futures"

    #     response = baseApi.post("/api/v2/mix/account/set-margin-mode", params)
    #     print(response)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)


    # Demo 下单
    # try:
    #     params = {}
    #     params["symbol"] = "BTCUSDT"
    #     params["marginCoin"] = "USDT"
    #     params["marginMode"] = "crossed"
    #     params["productType"] = "susdt-futures"
    #     params["side"] = "buy"
    #     params["orderType"] = "limit"
    #     params["price"] = "92300"
    #     params["size"] = "0.01"
    #     response = baseApi.post("/api/v2/mix/order/place-order", params)
    #     print(response)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)


    # Demo 获取品种精度
    # try:
    #     params = {}
    #     params["symbol"] = "BTCUSDT"
    #     params["productType"] = "USDT-FUTURES"
    #     response = baseApi.get("/api/v2/mix/market/contracts", params)
    #     print(response)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)


    # Demo 平仓
    try:
        params = {}
        params["symbol"] = "BTCUSDT"
        params["productType"] = "susdt-futures"
        # params["holdSide"] = "long"
        response = baseApi.post("/api/v2/mix/order/close-positions", params)
        print(response)
    except BitgetAPIException as e:
        print("error:" + e.message)


    # Demo 获取仓位信息
    # try:
    #     params = {}
    #     params["symbol"] = "BTCUSDT"
    #     params["productType"] = "SUSDT-FUTURES"
    #     params["marginCoin"] = "USDT"
    #     response = baseApi.get("/api/v2/mix/position/single-position", params)
    #     print(response)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)