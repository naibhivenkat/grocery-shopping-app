package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.databinding.ActivityOrderConfirmBinding
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import com.razorpay.Checkout
import com.razorpay.PaymentData
import com.razorpay.PaymentResultWithDataListener

class OrderConfirmActivity : AppCompatActivity(), PaymentResultWithDataListener {

    private lateinit var binding: ActivityOrderConfirmBinding

    private lateinit var cartItems: List<CartItem>
    private var totalAmount: Double = 0.0

    // pay-now / due
    private var payNowAmount: Double = 0.0
    private var dueAmount: Double = 0.0

    private var customerId: String? = null
    private var shopId: String? = null
    private var shopName: String = "Shop"

    // Spinner value ("UPI", "Cash", "Wallet")
    private var selectedPaymentLabel: String = "UPI"

    // These are used internally
    private lateinit var orderManager: OrderManager
    private lateinit var paymentManager: PaymentManager

    // IDs from backend + Razorpay
    private var backendOrderId: String? = null
    private var razorpayOrderId: String? = null

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

        // Get cart and total passed from CartActivity (or fallback to CartManager)
        cartItems = intent.getParcelableArrayListExtra<CartItem>("cart")
            ?: CartManager.getCart(shopId!!)

        totalAmount = intent.getDoubleExtra("total", 0.0)

        if (cartItems.isEmpty()) {
            Toast.makeText(this, "Cart is empty", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        // UI setup
        binding.textViewTotal.text = "Total: ₹%.2f".format(totalAmount)
        binding.textViewShopName.text = "Shop: $shopName"

        // Default: pay full amount
        payNowAmount = totalAmount
        dueAmount = 0.0
        binding.editTextPayNow.setText("%.2f".format(payNowAmount))
        binding.textViewDueAmount.text = "Due: ₹%.2f".format(dueAmount)

        // Payment methods shown to user
        val paymentMethods = listOf("UPI", "Cash", "Wallet")
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, paymentMethods)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        binding.paymentSpinner.adapter = adapter

        binding.paymentSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(
                parent: AdapterView<*>,
                view: View?,
                position: Int,
                id: Long
            ) {
                selectedPaymentLabel = paymentMethods[position]
            }

            override fun onNothingSelected(parent: AdapterView<*>) {}
        }

        // Listen for pay-now changes
        binding.editTextPayNow.addTextChangedListener(object : TextWatcher {
            override fun afterTextChanged(s: Editable?) {
                val text = s?.toString()?.trim() ?: ""

                payNowAmount = if (text.isNotEmpty()) {
                    text.toDoubleOrNull() ?: 0.0
                } else {
                    0.0
                }

                if (payNowAmount < 0) payNowAmount = 0.0
                if (payNowAmount > totalAmount) {
                    payNowAmount = totalAmount
                    binding.editTextPayNow.setText("%.2f".format(totalAmount))
                    binding.editTextPayNow.setSelection(binding.editTextPayNow.text.length)
                }

                dueAmount = totalAmount - payNowAmount
                binding.textViewDueAmount.text = "Due: ₹%.2f".format(dueAmount)
            }

            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
        })

        binding.buttonPlaceOrder.setOnClickListener {
            handlePlaceOrderClick()
        }
    }

    private fun handlePlaceOrderClick() {

        if (payNowAmount < 0) {
            Toast.makeText(this, "Invalid pay amount!", Toast.LENGTH_SHORT).show()
            return
        }

        if (payNowAmount == 0.0 && selectedPaymentLabel != "Cash") {
            // If they want to pay 0 now, then it should be pure Khata/Cash credit
            Toast.makeText(
                this,
                "Pay-now is 0. Use Cash (Khata) or enter an amount.",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        // Map spinner label to backend payment methods
        val backendPaymentMethod = when (selectedPaymentLabel) {
            "UPI" -> "Razorpay"
            "Cash" -> "Cash"
            "Wallet" -> "Wallet"
            else -> "Cash"
        }

        // For wallet, ensure they’re not trying to pay more than they have
        // (Backend also checks; this is just UX-friendly.)
        if (backendPaymentMethod == "Wallet" && payNowAmount <= 0.0) {
            Toast.makeText(this, "Enter an amount to pay with Wallet.", Toast.LENGTH_SHORT).show()
            return
        }

        // Place order with partial/full payment information
        orderManager.placeOrder(
            cartItems = cartItems,
            shopId = shopId!!,
            paymentMethod = backendPaymentMethod,
            transactionId = "",
            payNowAmount = payNowAmount,
            dueAmount = dueAmount
        )
    }

    /**
     * Called by OrderManager when /api/place_orders succeeds.
     * paymentMethod here is the backend value: "Razorpay", "Wallet", or "Cash".
     */
    fun onOrderPlacedSuccess(orderId: String?, razorpayOrderId: String?, paymentMethod: String) {

        backendOrderId = orderId
        this.razorpayOrderId = razorpayOrderId

        when (paymentMethod) {

            "Razorpay" -> {
                // For UPI, we MUST go through Razorpay flow.
                // Amount charged = payNowAmount (not the total).
                paymentManager.startRazorpayCheckout(
                    shopName,
                    payNowAmount,
                    razorpayOrderId
                )
            }

            "Wallet" -> {
                // Wallet already deducted on the backend at this point.
                Toast.makeText(this, "Paid using Wallet!", Toast.LENGTH_SHORT).show()
                CartManager.clearCart(shopId!!)
                goToThankYou()
            }

            else -> { // Cash
                // Pure cash or pure Khata (if payNowAmount = 0 and dueAmount = total)
                Toast.makeText(this, "Cash Order Placed!", Toast.LENGTH_SHORT).show()
                CartManager.clearCart(shopId!!)
                goToThankYou()
            }
        }
    }

    fun onOrderPlacedError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    // Razorpay success → verify with backend
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

    // Called by PaymentManager when /api/verify_payment says "OK"
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
