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
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import com.razorpay.Checkout
import com.razorpay.PaymentData
import com.razorpay.PaymentResultWithDataListener

class OrderConfirmActivity : AppCompatActivity(), PaymentResultWithDataListener {

    private lateinit var binding: ActivityOrderConfirmBinding
    private lateinit var cartItems: List<CartItem>
    private var totalAmount: Double = 0.0
    private var customerId: String? = null
    private var shopId: String? = null
    private var shopName: String = "Shop"
    private var selectedPaymentMethod: String = "UPI"

    // managers
    private lateinit var orderManager: OrderManager
    private lateinit var paymentManager: PaymentManager

    // stored ids
    var backendOrderId: String? = null
    var razorpayOrderId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOrderConfirmBinding.inflate(layoutInflater)
        setContentView(binding.root)

        Checkout.preload(applicationContext)

        orderManager = OrderManager(this)
        paymentManager = PaymentManager(this)

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

//        val paymentMethods = listOf("UPI", "Cash")
        val paymentMethods = listOf("UPI", "Cash", "Wallet")

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

            when (selectedPaymentMethod) {

                "UPI" -> {
                    orderManager.placeOrder(
                        cartItems,
                        shopId!!,
                        "Razorpay",
                        ""
                    )
                }

                "Cash" -> {
                    orderManager.placeOrder(
                        cartItems,
                        shopId!!,
                        "Cash",
                        "N/A"
                    )
                }

                "Wallet" -> {
                    orderManager.placeOrder(
                        cartItems,
                        shopId!!,
                        "Wallet",
                        ""
                    )
                }
            }
        }

    }


    fun onOrderPlacedSuccess(orderId: String?, razorpayOrderId: String?, paymentMethod: String) {

        backendOrderId = orderId
        this.razorpayOrderId = razorpayOrderId

        when (paymentMethod) {

            "Razorpay" -> {
                paymentManager.startRazorpayCheckout(
                    shopName,
                    totalAmount,
                    razorpayOrderId
                )
            }

            "Wallet" -> {
                Toast.makeText(this, "Paid using Wallet!", Toast.LENGTH_SHORT).show()
                CartManager.clearCart(shopId!!)
                goToThankYou()
            }

            else -> {  // Cash
                Toast.makeText(this, "Cash Order Placed!", Toast.LENGTH_SHORT).show()
                CartManager.clearCart(shopId!!)
                goToThankYou()
            }
        }
    }


    // callback from orderManager (failure)
    fun onOrderPlacedError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    // Razorpay payment success
    override fun onPaymentSuccess(razorpayPaymentID: String?, paymentData: PaymentData?) {
        paymentManager.verifyPayment(
            backendOrderId,
            razorpayPaymentID,
            paymentData?.orderId,
            paymentData?.signature
        )
    }

    // Razorpay failure
    override fun onPaymentError(code: Int, response: String?, paymentData: PaymentData?) {
        Toast.makeText(this, "Payment Failed: $response", Toast.LENGTH_SHORT).show()
    }

    // called from PaymentManager when verified
    fun onPaymentVerified() {
        Toast.makeText(this, "Payment Verified & Order Placed!", Toast.LENGTH_SHORT).show()
        CartManager.clearCart(shopId!!)
        goToThankYou()
    }

    private fun goToThankYou() {
        val intent = Intent(this, ThankYouActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
        startActivity(intent)
        finish()
    }
}
