package com.example.groceryshoppingapp

import android.widget.Toast
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.models.CreateOrderRequest
import com.example.groceryshoppingapp.models.OrderItemRequest
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class OrderManager(private val activity: OrderConfirmActivity) {

    fun placeOrder(cartItems: List<CartItem>, shopId: String, paymentMethod: String, transactionId: String) {
        val apiService = RetrofitClient.getInstance(activity).create(ApiService::class.java)

        val itemsList = cartItems.map { item ->
            OrderItemRequest(item_id = item.item.id, quantity = item.quantity)
        }

        val orderData = CreateOrderRequest(
            shopId = shopId,
            payment_method = paymentMethod,
            items = itemsList,
            transaction_id = transactionId
        )

        apiService.createOrder(orderData).enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                if (response.isSuccessful && response.body() != null) {
                    val body = response.body()!!
                    val backendOrderId = body["order_id"] as? String
                    val razorpayOrderId = body["razorpay_order_id"] as? String
                    activity.onOrderPlacedSuccess(backendOrderId, razorpayOrderId, paymentMethod)
                } else {
                    activity.onOrderPlacedError("Failed to place order. Try again!")
                }
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                activity.onOrderPlacedError("Network error: ${t.message}")
            }
        })
    }
}
