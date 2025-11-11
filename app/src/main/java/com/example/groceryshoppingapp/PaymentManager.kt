package com.example.groceryshoppingapp

import android.widget.Toast
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import com.razorpay.Checkout
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class PaymentManager(private val activity: OrderConfirmActivity) {

    fun startRazorpayCheckout(shopName: String, totalAmount: Double, razorpayOrderId: String?) {
        val checkout = Checkout()
        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR")

        val amountInPaise = (totalAmount * 100).toInt()
        val options = JSONObject()
        options.put("name", shopName)
        options.put("description", "Grocery Order")
        options.put("currency", "INR")
        options.put("amount", amountInPaise)
        options.put("order_id", razorpayOrderId)
        options.put("prefill.email", SessionManager.getEmail(activity))
        options.put("prefill.contact", SessionManager.getPhone(activity))

        try {
            checkout.open(activity, options)
        } catch (e: Exception) {
            Toast.makeText(activity, "Error starting payment: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    fun verifyPayment(
        backendOrderId: String?,
        paymentId: String?,
        rpOrderId: String?,
        rpSignature: String?
    ) {
        val apiService = RetrofitClient.getInstance(activity).create(ApiService::class.java)
        val verifyData = mapOf(
            "order_id" to (backendOrderId ?: ""),
            "razorpay_payment_id" to (paymentId ?: ""),
            "razorpay_order_id" to (rpOrderId ?: ""),
            "razorpay_signature" to (rpSignature ?: "")
        )

        apiService.verifyPayment(verifyData).enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                if (response.isSuccessful) {
                    activity.onPaymentVerified()
                } else {
                    Toast.makeText(activity, "Payment verification failed", Toast.LENGTH_LONG).show()
                }
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                Toast.makeText(activity, "Verification error: ${t.message}", Toast.LENGTH_LONG).show()
            }
        })
    }
}
