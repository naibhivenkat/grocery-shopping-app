package com.example.groceryshoppingapp

import android.app.Activity
import android.util.Log
import android.widget.Toast
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.network.WalletVerifyRequest
import com.example.groceryshoppingapp.utils.SessionManager
import com.razorpay.Checkout
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class PaymentManager(private val activity: Activity) {

    companion object {
        var lastRazorpayOrderId: String? = null
        var lastSignature: String? = null
    }

    // -------------------------------------------------------------
    // 1️⃣ ORDER PAYMENT CHECKOUT
    // -------------------------------------------------------------
    fun startRazorpayCheckout(
        shopName: String,
        totalAmount: Double,
        razorpayOrderId: String?
    ) {
        Log.e("PAYMENT_MANAGER", "=== startRazorpayCheckout ===")
        Log.e("PAYMENT_MANAGER", "shopName=$shopName")
        Log.e("PAYMENT_MANAGER", "totalAmount=$totalAmount")
        Log.e("PAYMENT_MANAGER", "razorpayOrderId=$razorpayOrderId")

        val checkout = Checkout()
        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR")

        val options = JSONObject()
        options.put("name", shopName)
        options.put("description", "Grocery Order")
        options.put("currency", "INR")
        options.put("amount", (totalAmount * 100).toInt())
        options.put("order_id", razorpayOrderId)

        val prefill = JSONObject()
        prefill.put("email", SessionManager.getEmail(activity))
        prefill.put("contact", SessionManager.getPhone(activity))
        options.put("prefill", prefill)

        checkout.open(activity, options)
    }

    // -------------------------------------------------------------
    // 2️⃣ WALLET TOP-UP CHECKOUT
    // -------------------------------------------------------------
    fun startWalletTopUp(amount: Double, razorpayOrderId: String?) {
        Log.e("PAYMENT_MANAGER", "=== startWalletTopUp ===")
        Log.e("PAYMENT_MANAGER", "amount=$amount")
        Log.e("PAYMENT_MANAGER", "razorpayOrderId=$razorpayOrderId")

        val checkout = Checkout()
        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR")

        val options = JSONObject()
        options.put("name", "Wallet Recharge")
        options.put("description", "Add Money to Wallet")
        options.put("currency", "INR")
        options.put("amount", (amount * 100).toInt())
        options.put("order_id", razorpayOrderId)

        val prefill = JSONObject()
        prefill.put("email", SessionManager.getEmail(activity))
        prefill.put("contact", SessionManager.getPhone(activity))
        options.put("prefill", prefill)

        checkout.open(activity, options)
    }

    // -------------------------------------------------------------
    // 3️⃣ UNIFIED VERIFY PAYMENT (ORDER + WALLET)
    // -------------------------------------------------------------
    fun verifyPayment(
        backendOrderId: String?,
        paymentId: String?,
        rpOrderId: String?,
        rpSignature: String?
    ) {

        Log.e("PAYMENT_MANAGER", "=== verifyPayment ===")
        Log.e("PAYMENT_MANAGER", "backendOrderId=$backendOrderId")
        Log.e("PAYMENT_MANAGER", "paymentId=$paymentId")
        Log.e("PAYMENT_MANAGER", "rpOrderId=$rpOrderId")
        Log.e("PAYMENT_MANAGER", "rpSignature=$rpSignature")
        Log.e("PAYMENT_MANAGER", "activity=${activity::class.java.simpleName}")

        val api = RetrofitClient.getInstance(activity).create(ApiService::class.java)

        // -------------------------------------------------------------
        // ORDER PAYMENT VERIFICATION
        // -------------------------------------------------------------
        if (activity is OrderConfirmActivity) {

            val verifyData = mapOf(
                "order_id" to (backendOrderId ?: ""),
                "razorpay_payment_id" to (paymentId ?: ""),
                "razorpay_order_id" to (rpOrderId ?: ""),
                "razorpay_signature" to (rpSignature ?: "")
            )

            Log.e("PAYMENT_MANAGER", "Sending verifyPayment (ORDER): $verifyData")

            api.verifyPayment(verifyData)
                .enqueue(object : Callback<Map<String, Any>> {

                    override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                        Log.e("PAYMENT_MANAGER", "ORDER verify response code=${response.code()}")
                        Log.e("PAYMENT_MANAGER", "ORDER verify body=${response.body()}")
                        Log.e("PAYMENT_MANAGER", "ORDER verify error=${response.errorBody()?.string()}")

                        if (response.isSuccessful) {
                            Log.e("PAYMENT_MANAGER", "Order verified successfully")
                            activity.onPaymentVerified()
                        } else {
                            Toast.makeText(activity, "Order payment verification failed", Toast.LENGTH_LONG).show()
                        }
                    }

                    override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                        Log.e("PAYMENT_MANAGER", "ORDER verify error=${t.message}")
                        Toast.makeText(activity, "Verify error: ${t.message}", Toast.LENGTH_LONG).show()
                    }
                })

            return
        }

        // -------------------------------------------------------------
        // WALLET TOP-UP VERIFICATION
        // -------------------------------------------------------------
        if (activity is WalletActivity) {

            val verifyWalletData = WalletVerifyRequest(
                backend_order_id = backendOrderId ?: "",
                payment_id = paymentId ?: "",
                order_id = rpOrderId ?: "",
                signature = rpSignature ?: ""
            )

            Log.e("PAYMENT_MANAGER", "Sending verifyWalletPayment: $verifyWalletData")

            api.verifyWalletPayment(verifyWalletData)
                .enqueue(object : Callback<Map<String, Any>> {

                    override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                        Log.e("PAYMENT_MANAGER", "WALLET verify response code=${response.code()}")
                        Log.e("PAYMENT_MANAGER", "WALLET verify body=${response.body()}")
                        Log.e("PAYMENT_MANAGER", "WALLET verify error=${response.errorBody()?.string()}")

                        if (response.isSuccessful) {
                            Log.e("PAYMENT_MANAGER", "Wallet payment verified successfully")
                            activity.onPaymentVerified()
                        } else {
                            Toast.makeText(activity, "Wallet payment verification failed", Toast.LENGTH_LONG).show()
                        }
                    }

                    override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                        Log.e("PAYMENT_MANAGER", "WALLET verify error=${t.message}")
                        Toast.makeText(activity, "Verification error: ${t.message}", Toast.LENGTH_LONG).show()
                    }
                })

            return
        }
    }
}
