import bitget.bitget_api as baseApi
import bitget.consts as bg_constants

from bitget.exceptions import BitgetAPIException

if __name__ == '__main__':
    apiKey = "bg_0fcc6babcd593ec94288b99a7445e196"
    secretKey = "8e715cf50188997531fa00c9e607f201a70e394b920e1986163e6e453475d10c"
    passphrase = "robin3910"
    baseApi = baseApi.BitgetApi(apiKey, secretKey, passphrase)


    # Demo 下单
#     {
#     "symbol": "SETHSUSDT",
#     "productType": "susdt-futures",
#     "marginMode": "isolated",
#     "marginCoin": "SUSDT",
#     "size": "1.5",
#     "price": "2000",
#     "side": "buy",
#     "tradeSide": "open",
#     "orderType": "limit",
#     "force": "gtc",
#     "clientOid": "12121212122",
#     "reduceOnly": "NO",
#     "presetStopSurplusPrice": "2300",
#     "presetStopLossPrice": "1800"
# }
    try:
        params = {}
        params["symbol"] = "BTCUSDT"
        params["marginCoin"] = "USDT"
        params["marginMode"] = "crossed"
        params["productType"] = "usdt-futures"
        params["side"] = "buy"
        params["orderType"] = "limit"
        params["force"] = "gtc"
        params["price"] = "97561.0"
        params["size"] = "0.05"
        response = baseApi.post("/api/v2/mix/order/place-order", params)
        print(response)
    except BitgetAPIException as e:
        print("error:" + e.message)
