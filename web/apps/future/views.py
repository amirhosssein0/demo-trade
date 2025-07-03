from django.shortcuts import render
from django.http import JsonResponse
from .models import FuturesOrders
from django.views.decorators.csrf import csrf_exempt
from exchange.models import Portfolio

# Create your views here.

def futures_live_report(request):
    return render(request, 'futures_live_report.html')

@csrf_exempt
def create_futures_order(request):
    if request.method == "POST":
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({"error": "login required"}, status=403)
        data = request.POST
        amount = float(data.get("amount").split()[0])
        leverage = int(data.get("leverage"))
        entry_price = float(data.get("entryPrice"))
        total_volume = amount * entry_price * leverage
        fee = total_volume * 0.01
        # کم کردن فی از موجودی کاربر
        try:
            portfolio = Portfolio.objects.get(usr=user, cryptoName="USDT", marketType="futures")
        except Portfolio.DoesNotExist:
            return JsonResponse({"error": "No futures USDT balance"}, status=400)
        if portfolio.amount < fee:
            return JsonResponse({"error": "Insufficient balance for fee"}, status=400)
        portfolio.amount -= fee
        portfolio.save()
        order = FuturesOrders.objects.create(
            usr=user,
            type=data.get("type"),
            pair=data.get("pair"),
            amount=data.get("amount"),
            entryPrice=entry_price,
            marketPrice=float(data.get("marketPrice")),
            liqPrice=float(data.get("liqPrice")),
            leverage=leverage,
            orderType=data.get("orderType"),
            marginType=data.get("marginType"),
            complete=False,
            fee=fee,
        )
        return JsonResponse({"success": True, "order_id": order.id, "fee": fee})
    return JsonResponse({"error": "POST only"}, status=405)
