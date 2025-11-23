//package com.example.groceryshoppingapp
//
//import android.widget.Toast
//import com.example.groceryshoppingapp.network.ApiService
//import com.example.groceryshoppingapp.network.RetrofitClient
//import com.example.groceryshoppingapp.utils.SessionManager
//import com.razorpay.Checkout
//import org.json.JSONObject
//import retrofit2.Call
//import retrofit2.Callback
//import retrofit2.Response
//
//class PaymentManager(private val activity: OrderConfirmActivity) {
//
//    fun startRazorpayCheckout(shopName: String, totalAmount: Double, razorpayOrderId: String?) {
//        val checkout = Checkout()
//        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR")
//
//        val amountInPaise = (totalAmount * 100).toInt()
//        val options = JSONObject()
//        options.put("name", shopName)
//        options.put("description", "Grocery Order")
//        options.put("currency", "INR")
//        options.put("amount", amountInPaise)
//        options.put("order_id", razorpayOrderId)
//        options.put("prefill.email", SessionManager.getEmail(activity))
//        options.put("prefill.contact", SessionManager.getPhone(activity))
//
//        try {
//            checkout.open(activity, options)
//        } catch (e: Exception) {
//            Toast.makeText(activity, "Error starting payment: ${e.message}", Toast.LENGTH_LONG).show()
//        }
//    }
//
//    fun verifyPayment(
//        backendOrderId: String?,
//        paymentId: String?,
//        rpOrderId: String?,
//        rpSignature: String?
//    ) {
//        val apiService = RetrofitClient.getInstance(activity).create(ApiService::class.java)
//        val verifyData = mapOf(
//            "order_id" to (backendOrderId ?: ""),
//            "razorpay_payment_id" to (paymentId ?: ""),
//            "razorpay_order_id" to (rpOrderId ?: ""),
//            "razorpay_signature" to (rpSignature ?: "")
//        )
//
//        apiService.verifyPayment(verifyData).enqueue(object : Callback<Map<String, Any>> {
//            override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
//                if (response.isSuccessful) {
//                    activity.onPaymentVerified()
//                } else {
//                    Toast.makeText(activity, "Payment verification failed", Toast.LENGTH_LONG).show()
//                }
//            }
//
//            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
//                Toast.makeText(activity, "Verification error: ${t.message}", Toast.LENGTH_LONG).show()
//            }
//        })
//    }
//}
//package com.example.groceryshoppingapp
//
//import android.widget.Toast
//import com.example.groceryshoppingapp.network.ApiService
//import com.example.groceryshoppingapp.network.RetrofitClient
//import com.example.groceryshoppingapp.utils.SessionManager
//import com.razorpay.Checkout
//import org.json.JSONObject
//import retrofit2.Call
//import retrofit2.Callback
//import retrofit2.Response
//
//class PaymentManager(private val activity: OrderConfirmActivity) {
//
//    companion object {
//        var lastRazorpayOrderId: String? = null
//        var lastSignature: String? = null
//    }
//
//
//    // ---------------------------------------------------------
//    // ORIGINAL ORDER PAYMENT METHOD (UNTOUCHED)
//    // ---------------------------------------------------------
//    fun startRazorpayCheckout(shopName: String, totalAmount: Double, razorpayOrderId: String?) {
//        val checkout = Checkout()
//        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR")
//
//        val amountInPaise = (totalAmount * 100).toInt()
//        val options = JSONObject()
//        options.put("name", shopName)
//        options.put("description", "Grocery Order")
//        options.put("currency", "INR")
//        options.put("amount", amountInPaise)
//        options.put("order_id", razorpayOrderId)
//        options.put("prefill.email", SessionManager.getEmail(activity))
//        options.put("prefill.contact", SessionManager.getPhone(activity))
//
//        try {
//            checkout.open(activity, options)
//        } catch (e: Exception) {
//            Toast.makeText(activity, "Error starting payment: ${e.message}", Toast.LENGTH_LONG).show()
//        }
//    }
//
//    // ---------------------------------------------------------
//    // 🔥 NEW: WALLET TOP-UP PAYMENT (MINIMAL ADDITION)
//    // ---------------------------------------------------------
//    fun startWalletTopUp(amount: Double) {
//        val checkout = Checkout()
//        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR")
//
//        try {
//            val options = JSONObject()
//            options.put("name", "Grocery App Wallet")
//            options.put("description", "Wallet Top-up")
//            options.put("currency", "INR")
//            options.put("amount", (amount * 100).toInt())
//
//            val prefill = JSONObject()
//            prefill.put("email", SessionManager.getEmail(activity))
//            prefill.put("contact", SessionManager.getPhone(activity))
//            options.put("prefill", prefill)
//
//            checkout.open(activity, options)
//
//        } catch (e: Exception) {
//            e.printStackTrace()
//            Toast.makeText(activity, "Error starting wallet payment", Toast.LENGTH_SHORT).show()
//        }
//    }
//
//    // ---------------------------------------------------------
//    // ORIGINAL VERIFY PAYMENT (UNTOUCHED)
//    // ---------------------------------------------------------
//    fun verifyPayment(
//        backendOrderId: String?,
//        paymentId: String?,
//        rpOrderId: String?,
//        rpSignature: String?
//    ) {
//        val apiService = RetrofitClient.getInstance(activity).create(ApiService::class.java)
//        val verifyData = mapOf(
//            "order_id" to (backendOrderId ?: ""),
//            "razorpay_payment_id" to (paymentId ?: ""),
//            "razorpay_order_id" to (rpOrderId ?: ""),
//            "razorpay_signature" to (rpSignature ?: "")
//        )
//
//        apiService.verifyPayment(verifyData).enqueue(object : Callback<Map<String, Any>> {
//            override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
//                if (response.isSuccessful) {
//                    activity.onPaymentVerified()
//                } else {
//                    Toast.makeText(activity, "Payment verification failed", Toast.LENGTH_LONG).show()
//                }
//            }
//
//            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
//                Toast.makeText(activity, "Verification error: ${t.message}", Toast.LENGTH_LONG).show()
//            }
//        })
//    }
//}


package com.example.groceryshoppingapp

import android.app.Activity
import android.widget.Toast
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import com.razorpay.Checkout
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class PaymentManager(private val activity: Activity) {

    companion object {
        // Optional storage if some other code wants to set/read these.
        var lastRazorpayOrderId: String? = null
        var lastSignature: String? = null
    }

    // ----------------------------------------------------------------
    // Original Order payment method (kept behavior)
    // ----------------------------------------------------------------
    fun startRazorpayCheckout(
        shopName: String,
        totalAmount: Double,
        razorpayOrderId: String?
    ) {
        val checkout = Checkout()
        // 🔧 FIX: kept same key id as your code. Replace with prod key when ready.
        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR")

        val amountInPaise = (totalAmount * 100).toInt()
        val options = JSONObject()
        options.put("name", shopName)
        options.put("description", "Grocery Order")
        options.put("currency", "INR")
        options.put("amount", amountInPaise)
        options.put("order_id", razorpayOrderId)

        val prefill = JSONObject()
        prefill.put("email", SessionManager.getEmail(activity))
        prefill.put("contact", SessionManager.getPhone(activity))
        options.put("prefill", prefill)

        try {
            checkout.open(activity, options)
        } catch (e: Exception) {
            Toast.makeText(activity, "Error starting payment: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    // ----------------------------------------------------------------
    // Minimal addition for wallet top-up (safe)
    // ----------------------------------------------------------------
    fun startWalletTopUp(amount: Double) {
        val checkout = Checkout()
        // 🔧 FIX: reuse same test key. Replace with real key in prod.
        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR")

        try {
            val options = JSONObject()
            options.put("name", "Grocery App Wallet")
            options.put("description", "Wallet Top-up")
            options.put("currency", "INR")
            options.put("amount", (amount * 100).toInt())

            val prefill = JSONObject()
            prefill.put("email", SessionManager.getEmail(activity))
            prefill.put("contact", SessionManager.getPhone(activity))
            options.put("prefill", prefill)

            checkout.open(activity, options)
        } catch (e: Exception) {
            e.printStackTrace()
            Toast.makeText(activity, "Error starting wallet payment", Toast.LENGTH_SHORT).show()
        }
    }

    // ----------------------------------------------------------------
    // Verify payment with backend (unchanged behavior, small safety)
    // ----------------------------------------------------------------
    fun verifyPayment(
        backendOrderId: String?,
        paymentId: String?,
        rpOrderId: String?,
        rpSignature: String?
    ) {
        val apiService = RetrofitClient.getInstance(activity)
            .create(ApiService::class.java)

        val verifyData = mapOf(
            "order_id" to (backendOrderId ?: ""),
            "razorpay_payment_id" to (paymentId ?: ""),
            "razorpay_order_id" to (rpOrderId ?: ""),
            "razorpay_signature" to (rpSignature ?: "")
        )

        apiService.verifyPayment(verifyData)
            .enqueue(object : Callback<Map<String, Any>> {
                override fun onResponse(
                    call: Call<Map<String, Any>>,
                    response: Response<Map<String, Any>>
                ) {
                    if (response.isSuccessful) {
                        // 🔧 FIX: call back to the activity that initiated payment - supports both screens
                        when (activity) {
                            is OrderConfirmActivity -> activity.onPaymentVerified()
                            is WalletActivity -> activity.onPaymentVerified()
                        }
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
