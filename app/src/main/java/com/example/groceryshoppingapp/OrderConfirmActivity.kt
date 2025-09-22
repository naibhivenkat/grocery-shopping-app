package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.databinding.ActivityOrderConfirmBinding
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.models.CreateOrderRequest
import com.example.groceryshoppingapp.models.OrderItemRequest
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import com.razorpay.Checkout
import com.razorpay.PaymentResultWithDataListener
import com.razorpay.PaymentData
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class OrderConfirmActivity : AppCompatActivity(), PaymentResultWithDataListener {

    private lateinit var binding: ActivityOrderConfirmBinding
    private lateinit var cartItems: List<CartItem>
    private var totalAmount: Double = 0.0
    private var customerId: String? = null
    private var shopId: String? = null
    private var shopName: String = "Shop"
    private var selectedPaymentMethod: String = "UPI" // default option

    // 🔹 Store order data for later verify
    private var backendOrderId: String? = null
    private var razorpayOrderId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOrderConfirmBinding.inflate(layoutInflater)
        setContentView(binding.root)

        Checkout.preload(applicationContext)

        customerId = SessionManager.getCustomerId(this)
        shopId = intent.getStringExtra("SHOP_ID") ?: SessionManager.getShopId(this)
        shopName = SessionManager.getShopName(this) ?: "Shop"

        if (customerId.isNullOrEmpty() || shopId.isNullOrEmpty()) {
            Toast.makeText(this, "Session expired. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        cartItems = intent.getParcelableArrayListExtra("cart") ?: CartManager.getCart(shopId!!)
        totalAmount = intent.getDoubleExtra("total", 0.0)

        if (cartItems.isEmpty()) {
            Toast.makeText(this, "Cart is empty", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        binding.textViewTotal.text = "Total: ₹%.2f".format(totalAmount)
        binding.textViewShopName.text = "Shop: $shopName"

        val paymentMethods = listOf("UPI", "Cash")
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, paymentMethods)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        binding.paymentSpinner.adapter = adapter

        binding.paymentSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>, view: View?, position: Int, id: Long) {
                selectedPaymentMethod = paymentMethods[position]
            }
            override fun onNothingSelected(parent: AdapterView<*>) {}
        }

        binding.buttonPlaceOrder.setOnClickListener {
            if (selectedPaymentMethod == "UPI") {
                placeOrder("Razorpay", "") // first create order on backend
            } else {
                placeOrder("Cash", "N/A")
            }
        }
    }

    // 🔹 Place order (backend call)
    private fun placeOrder(paymentMethod: String, transactionId: String) {
        val apiService = RetrofitClient.getInstance(this).create(ApiService::class.java)

        val itemsList = cartItems.map { item ->
            OrderItemRequest(
                item_id = item.item.id,
                quantity = item.quantity
            )
        }

        val orderData = CreateOrderRequest(
            shopId = shopId!!,
            payment_method = paymentMethod,
            items = itemsList,
            transaction_id = transactionId
        )

        apiService.createOrder(orderData).enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                if (response.isSuccessful && response.body() != null) {
                    val body = response.body()!!
                    backendOrderId = body["order_id"] as? String
                    razorpayOrderId = body["razorpay_order_id"] as? String

                    if (paymentMethod == "Razorpay") {
                        startRazorpayCheckout()
                    } else {
                        Toast.makeText(this@OrderConfirmActivity, "Cash Order Placed!", Toast.LENGTH_SHORT).show()
                        CartManager.clearCart(shopId!!)
                        goToThankYou()
                    }
                } else {
                    Toast.makeText(this@OrderConfirmActivity, "Failed to place order. Try again!", Toast.LENGTH_LONG).show()
                }
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                Toast.makeText(this@OrderConfirmActivity, "Network error: ${t.message}", Toast.LENGTH_LONG).show()
            }
        })
    }

    // 🔹 Razorpay Checkout
    private fun startRazorpayCheckout() {
        val checkout = Checkout()
        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR") // replace with your key

        val amountInPaise = (totalAmount * 100).toInt()
        val options = JSONObject()
        options.put("name", shopName)
        options.put("description", "Grocery Order")
        options.put("currency", "INR")
        options.put("amount", amountInPaise)
        options.put("order_id", razorpayOrderId) // ✅ link backend order

        options.put("prefill.email", SessionManager.getEmail(this))
        options.put("prefill.contact", SessionManager.getPhone(this))

        checkout.open(this, options)
    }

    // 🔹 Payment success (with payment data)
    override fun onPaymentSuccess(razorpayPaymentID: String?, paymentData: PaymentData?) {
        Toast.makeText(this, "Payment Successful", Toast.LENGTH_SHORT).show()

        val paymentId = razorpayPaymentID ?: ""
        val rpOrderId = paymentData?.orderId ?: ""
        val rpSignature = paymentData?.signature ?: ""

        verifyPayment(paymentId, rpOrderId, rpSignature)
    }

    override fun onPaymentError(code: Int, response: String?, paymentData: PaymentData?) {
        Toast.makeText(this, "Payment Failed: $response", Toast.LENGTH_SHORT).show()
    }

    // 🔹 Verify Payment API
    private fun verifyPayment(paymentId: String, rpOrderId: String, rpSignature: String) {
        val apiService = RetrofitClient.getInstance(this).create(ApiService::class.java)

        val verifyData = mapOf(
            "order_id" to (backendOrderId ?: ""),
            "razorpay_payment_id" to paymentId,
            "razorpay_order_id" to rpOrderId,
            "razorpay_signature" to rpSignature
        )

        apiService.verifyPayment(verifyData).enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                if (response.isSuccessful) {
                    Toast.makeText(this@OrderConfirmActivity, "Payment Verified & Order Placed!", Toast.LENGTH_SHORT).show()
                    CartManager.clearCart(shopId!!)
                    goToThankYou()
                } else {
                    Toast.makeText(this@OrderConfirmActivity, "Payment verification failed", Toast.LENGTH_LONG).show()
                }
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                Toast.makeText(this@OrderConfirmActivity, "Verification error: ${t.message}", Toast.LENGTH_LONG).show()
            }
        })
    }

    private fun goToThankYou() {
        val intent = Intent(this@OrderConfirmActivity, ThankYouActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
        startActivity(intent)
        finish()
    }
}
