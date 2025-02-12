import bitget.v1.mix.order_api as maxOrderApi
import bitget.bitget_api as baseApi
import bitget.consts as bg_constants

from bitget.exceptions import BitgetAPIException

if __name__ == '__main__':
    apiKey = "bg_0fcc6babcd593ec94288b99a7445e196"
    secretKey = "8e715cf50188997531fa00c9e607f201a70e394b920e1986163e6e453475d10c"
    passphrase = "robin3910"
    baseApi = baseApi.BitgetApi(apiKey, secretKey, passphrase)

    # # Demo 1:place order
    # maxOrderApi = maxOrderApi.OrderApi(apiKey, secretKey, passphrase)
    # try:
    #     params = {}
    #     params["symbol"] = "BTCUSDT_UMCBL"
    #     params["marginCoin"] = "USDT"
    #     params["side"] = "open_long"
    #     params["orderType"] = "limit"
    #     params["price"] = "27012"
    #     params["size"] = "0.01"
    #     params["timInForceValue"] = "normal"
    #     response = maxOrderApi.placeOrder(params)
    #     print(response)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)

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


    # Demo 2:place order by post directly
    # try:
    #     params = {}
    #     params["symbol"] = "BTCUSDT"
    #     params["marginCoin"] = "USDT"
    #     params["marginMode"] = "crossed"
    #     params["productType"] = bg_constants.PRODUCT_TYPE
    #     params["side"] = "buy"
    #     params["orderType"] = "limit"
    #     params["price"] = "96700"
    #     params["size"] = "0.01"
    #     response = baseApi.post("/api/v2/mix/order/place-order", params)
    #     print(response)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)

    # Demo 3:send get request
    # try:
    #     params = {}
    #     params["productType"] = "umcbl"
    #     response = baseApi.get("/api/mix/v1/market/contracts", params)
    #     print(response)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)

    # Demo 4:send get request with no params
    # try:
    #     response = baseApi.get("/api/spot/v1/account/getInfo", {})
    #     print(response)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)

    # # Demo 5:send get request
    # try:
    #     params = {}
    #     params["symbol"] = "AIUSDT"
    #     params["businessType"] = "spot"
    #     response = baseApi.get("/api/v2/common/trade-rate", params)
    #     print(response)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)


    # Demo 获取品种精度
    try:
        params = {}
        params["symbol"] = "BTCUSDT"
        params["productType"] = "USDT-FUTURES"
        response = baseApi.get("/api/v2/mix/market/contracts", params)
        print(response)
    except BitgetAPIException as e:
        print("error:" + e.message)