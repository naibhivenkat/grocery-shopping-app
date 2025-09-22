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
import com.razorpay.PaymentResultListener
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class OrderConfirmActivity : AppCompatActivity(), PaymentResultListener {

    private lateinit var binding: ActivityOrderConfirmBinding
    private lateinit var cartItems: List<CartItem>
    private var totalAmount: Double = 0.0
    private var customerId: String? = null
    private var shopId: String? = null
    private var shopName: String = "Shop"
    private var selectedPaymentMethod: String = "UPI" // default option

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOrderConfirmBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Init Razorpay (only needed if UPI is used)
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

        // 🔹 Setup payment options spinner
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

        // 🔹 Place order button click
        binding.buttonPlaceOrder.setOnClickListener {
            if (selectedPaymentMethod == "UPI") {
                startRazorpayCheckout()
            } else if (selectedPaymentMethod == "Cash") {
                placeOrder("Cash", "N/A") // no transaction id for cash
            }
        }
    }

    private fun startRazorpayCheckout() {
        val checkout = Checkout()
        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR") // Replace with your key

        val amountInPaise = (totalAmount * 100).toInt() // Razorpay needs amount in paise
        val options = JSONObject()
        options.put("name", shopName)
        options.put("description", "Grocery Order")
        options.put("currency", "INR")
        options.put("amount", amountInPaise)
        options.put("prefill.email", SessionManager.getEmail(this))
        options.put("prefill.contact", SessionManager.getPhone(this))

        checkout.open(this, options)
    }

    // 🔹 Razorpay payment success
    override fun onPaymentSuccess(razorpayPaymentID: String) {
        Toast.makeText(this, "Payment Successful", Toast.LENGTH_SHORT).show()
        placeOrder("Razorpay", razorpayPaymentID)
    }

    // 🔹 Razorpay payment failed
    override fun onPaymentError(code: Int, response: String?) {
        Toast.makeText(this, "Payment Failed: $response", Toast.LENGTH_SHORT).show()
    }

    // 🔹 Place order on backend
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
                if (response.isSuccessful) {
                    if (paymentMethod == "Razorpay") {
                        // 🔹 Call verify endpoint for Razorpay
                        verifyPayment(transactionId)
                    } else {
                        // 🔹 Cash order directly confirmed
                        Toast.makeText(this@OrderConfirmActivity, "Cash Order Placed!", Toast.LENGTH_SHORT).show()
                        CartManager.clearCart(shopId!!)
                        val intent = Intent(this@OrderConfirmActivity, ThankYouActivity::class.java)
                        intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
                        startActivity(intent)
                        finish()
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

    private fun verifyPayment(paymentId: String) {
        val apiService = RetrofitClient.getInstance(this).create(ApiService::class.java)
        val verifyData = mapOf(
            "order_id" to "", // if you store order_id from createOrder response, put here
            "razorpay_payment_id" to paymentId,
            "razorpay_order_id" to "", // if available
            "razorpay_signature" to "" // optional
        )

        apiService.verifyPayment(verifyData).enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                if (response.isSuccessful) {
                    Toast.makeText(this@OrderConfirmActivity, "Payment Verified & Order Placed!", Toast.LENGTH_SHORT).show()
                    CartManager.clearCart(shopId!!)
                    val intent = Intent(this@OrderConfirmActivity, ThankYouActivity::class.java)
                    intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
                    startActivity(intent)
                    finish()
                } else {
                    Toast.makeText(this@OrderConfirmActivity, "Payment verification failed", Toast.LENGTH_LONG).show()
                }
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                Toast.makeText(this@OrderConfirmActivity, "Verification network error: ${t.message}", Toast.LENGTH_LONG).show()
            }
        })
    }
}
