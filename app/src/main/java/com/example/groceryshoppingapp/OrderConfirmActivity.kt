//package com.example.groceryshoppingapp
//
//import android.content.Intent
//import android.os.Bundle
//import android.text.Editable
//import android.text.TextWatcher
//import android.view.View
//import android.widget.AdapterView
//import android.widget.ArrayAdapter
//import android.widget.Toast
//import androidx.appcompat.app.AppCompatActivity
//import com.example.groceryshoppingapp.databinding.ActivityOrderConfirmBinding
//import com.example.groceryshoppingapp.models.CartItem
//import com.example.groceryshoppingapp.util.CartManager
//import com.example.groceryshoppingapp.utils.SessionManager
//import com.razorpay.Checkout
//import com.razorpay.PaymentData
//import com.razorpay.PaymentResultWithDataListener
//
//class OrderConfirmActivity : AppCompatActivity(), PaymentResultWithDataListener {
//
//    private lateinit var binding: ActivityOrderConfirmBinding
//
//    private lateinit var cartItems: List<CartItem>
//    private var totalAmount: Double = 0.0
//
//    // pay-now / due
//    private var payNowAmount: Double = 0.0
//    private var dueAmount: Double = 0.0
//
//    private var customerId: String? = null
//    private var shopId: String? = null
//    private var shopName: String = "Shop"
//
//    // Spinner value ("UPI", "Cash", "Wallet")
//    private var selectedPaymentLabel: String = "UPI"
//
//    // These are used internally
//    private lateinit var orderManager: OrderManager
//    private lateinit var paymentManager: PaymentManager
//
//    // IDs from backend + Razorpay
//    private var backendOrderId: String? = null
//    private var razorpayOrderId: String? = null
//
//    override fun onCreate(savedInstanceState: Bundle?) {
//        super.onCreate(savedInstanceState)
//        binding = ActivityOrderConfirmBinding.inflate(layoutInflater)
//        setContentView(binding.root)
//
//        Checkout.preload(applicationContext)
//
//        orderManager = OrderManager(this)
//        paymentManager = PaymentManager(this)
//
//        customerId = SessionManager.getCustomerId(this)
//        shopId = intent.getStringExtra("SHOP_ID") ?: SessionManager.getShopId(this)
//        shopName = SessionManager.getShopName(this) ?: "Shop"
//
//        if (customerId.isNullOrEmpty() || shopId.isNullOrEmpty()) {
//            Toast.makeText(this, "Session expired. Please login again.", Toast.LENGTH_SHORT).show()
//            startActivity(Intent(this, LoginActivity::class.java))
//            finish()
//            return
//        }
//
//        // Get cart and total passed from CartActivity (or fallback to CartManager)
//        cartItems = intent.getParcelableArrayListExtra<CartItem>("cart")
//            ?: CartManager.getCart(shopId!!)
//
//        totalAmount = intent.getDoubleExtra("total", 0.0)
//
//        if (cartItems.isEmpty()) {
//            Toast.makeText(this, "Cart is empty", Toast.LENGTH_SHORT).show()
//            finish()
//            return
//        }
//
//        // UI setup
//        binding.textViewTotal.text = "Total: ₹%.2f".format(totalAmount)
//        binding.textViewShopName.text = "Shop: $shopName"
//
//        // Default: pay full amount
//        payNowAmount = totalAmount
//        dueAmount = 0.0
//        binding.editTextPayNow.setText("%.2f".format(payNowAmount))
//        binding.textViewDueAmount.text = "Due: ₹%.2f".format(dueAmount)
//
//        // Payment methods shown to user
//        val paymentMethods = listOf("UPI", "Cash", "Wallet")
//        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, paymentMethods)
//        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
//        binding.paymentSpinner.adapter = adapter
//
//        binding.paymentSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
//            override fun onItemSelected(
//                parent: AdapterView<*>,
//                view: View?,
//                position: Int,
//                id: Long
//            ) {
//                selectedPaymentLabel = paymentMethods[position]
//            }
//
//            override fun onNothingSelected(parent: AdapterView<*>) {}
//        }
//
//        // Listen for pay-now changes
//        binding.editTextPayNow.addTextChangedListener(object : TextWatcher {
//            override fun afterTextChanged(s: Editable?) {
//                val text = s?.toString()?.trim() ?: ""
//
//                payNowAmount = if (text.isNotEmpty()) {
//                    text.toDoubleOrNull() ?: 0.0
//                } else {
//                    0.0
//                }
//
//                if (payNowAmount < 0) payNowAmount = 0.0
//                if (payNowAmount > totalAmount) {
//                    payNowAmount = totalAmount
//                    binding.editTextPayNow.setText("%.2f".format(totalAmount))
//                    binding.editTextPayNow.setSelection(binding.editTextPayNow.text.length)
//                }
//
//                dueAmount = totalAmount - payNowAmount
//                binding.textViewDueAmount.text = "Due: ₹%.2f".format(dueAmount)
//            }
//
//            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
//            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
//        })
//
//        binding.buttonPlaceOrder.setOnClickListener {
//            handlePlaceOrderClick()
//        }
//    }
//
//    private fun handlePlaceOrderClick() {
//
//        if (payNowAmount < 0) {
//            Toast.makeText(this, "Invalid pay amount!", Toast.LENGTH_SHORT).show()
//            return
//        }
//
//        if (payNowAmount == 0.0 && selectedPaymentLabel != "Cash") {
//            // If they want to pay 0 now, then it should be pure Khata/Cash credit
//            Toast.makeText(
//                this,
//                "Pay-now is 0. Use Cash (Khata) or enter an amount.",
//                Toast.LENGTH_LONG
//            ).show()
//            return
//        }
//
//        // Map spinner label to backend payment methods
//        val backendPaymentMethod = when (selectedPaymentLabel) {
//            "UPI" -> "Razorpay"
//            "Cash" -> "Cash"
//            "Wallet" -> "Wallet"
//            else -> "Cash"
//        }
//
//        // For wallet, ensure they’re not trying to pay more than they have
//        // (Backend also checks; this is just UX-friendly.)
//        if (backendPaymentMethod == "Wallet" && payNowAmount <= 0.0) {
//            Toast.makeText(this, "Enter an amount to pay with Wallet.", Toast.LENGTH_SHORT).show()
//            return
//        }
//
//        // Place order with partial/full payment information
//        orderManager.placeOrder(
//            cartItems = cartItems,
//            shopId = shopId!!,
//            paymentMethod = backendPaymentMethod,
//            transactionId = "",
//            payNowAmount = payNowAmount,
//            dueAmount = dueAmount
//        )
//    }
//
//    /**
//     * Called by OrderManager when /api/place_orders succeeds.
//     * paymentMethod here is the backend value: "Razorpay", "Wallet", or "Cash".
//     */
//    fun onOrderPlacedSuccess(orderId: String?, razorpayOrderId: String?, paymentMethod: String) {
//
//        backendOrderId = orderId
//        this.razorpayOrderId = razorpayOrderId
//
//        when (paymentMethod) {
//
//            "Razorpay" -> {
//                // For UPI, we MUST go through Razorpay flow.
//                // Amount charged = payNowAmount (not the total).
//                paymentManager.startRazorpayCheckout(
//                    shopName,
//                    payNowAmount,
//                    razorpayOrderId
//                )
//            }
//
//            "Wallet" -> {
//                // Wallet already deducted on the backend at this point.
//                Toast.makeText(this, "Paid using Wallet!", Toast.LENGTH_SHORT).show()
//                CartManager.clearCart(shopId!!)
//                goToThankYou()
//            }
//
//            else -> { // Cash
//                // Pure cash or pure Khata (if payNowAmount = 0 and dueAmount = total)
//                Toast.makeText(this, "Cash Order Placed!", Toast.LENGTH_SHORT).show()
//                CartManager.clearCart(shopId!!)
//                goToThankYou()
//            }
//        }
//    }
//
//    fun onOrderPlacedError(message: String) {
//        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
//    }
//
//    // Razorpay success → verify with backend
//    override fun onPaymentSuccess(razorpayPaymentID: String?, paymentData: PaymentData?) {
//        paymentManager.verifyPayment(
//            backendOrderId,
//            razorpayPaymentID,
//            paymentData?.orderId,
//            paymentData?.signature
//        )
//    }
//
//    // Razorpay failure
//    override fun onPaymentError(code: Int, response: String?, paymentData: PaymentData?) {
//        Toast.makeText(this, "Payment Failed: $response", Toast.LENGTH_SHORT).show()
//    }
//
//    // Called by PaymentManager when /api/verify_payment says "OK"
//    fun onPaymentVerified() {
//        Toast.makeText(this, "Payment Verified & Order Placed!", Toast.LENGTH_SHORT).show()
//        CartManager.clearCart(shopId!!)
//        goToThankYou()
//    }
//
//    private fun goToThankYou() {
//        val intent = Intent(this, ThankYouActivity::class.java)
//        intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
//        startActivity(intent)
//        finish()
//    }
//}

//package com.example.groceryshoppingapp
//
//import android.content.Intent
//import android.os.Bundle
//import android.text.Editable
//import android.text.TextWatcher
//import android.view.View
//import android.widget.Toast
//import androidx.appcompat.app.AppCompatActivity
//import androidx.core.content.ContextCompat
//import com.example.groceryshoppingapp.databinding.ActivityOrderConfirmBinding
//import com.example.groceryshoppingapp.models.CartItem
//import com.example.groceryshoppingapp.models.WalletBalanceResponse
//import com.example.groceryshoppingapp.network.ApiService
//import com.example.groceryshoppingapp.network.RetrofitClient
//import com.example.groceryshoppingapp.util.CartManager
//import com.example.groceryshoppingapp.utils.SessionManager
//import com.razorpay.Checkout
//import com.razorpay.PaymentData
//import com.razorpay.PaymentResultWithDataListener
//import retrofit2.Call
//import retrofit2.Callback
//import retrofit2.Response
//
//class OrderConfirmActivity : AppCompatActivity(), PaymentResultWithDataListener {
//
//    private lateinit var binding: ActivityOrderConfirmBinding
//
//    private lateinit var cartItems: List<CartItem>
//    private var totalAmount = 0.0
//    private var payNowAmount = 0.0
//    private var dueAmount = 0.0
//
//    private var customerId: String? = null
//    private var shopId: String? = null
//    private var shopName = "Shop"
//
//    private var selectedPaymentLabel = "UPI"
//    private var walletBalance = 0.0
//
//    private lateinit var orderManager: OrderManager
//    private lateinit var paymentManager: PaymentManager
//
//    private var backendOrderId: String? = null
//    private var razorpayOrderId: String? = null
//
//    override fun onCreate(savedInstanceState: Bundle?) {
//        super.onCreate(savedInstanceState)
//        binding = ActivityOrderConfirmBinding.inflate(layoutInflater)
//        setContentView(binding.root)
//
//        Checkout.preload(applicationContext)
//
//        orderManager = OrderManager(this)
//        paymentManager = PaymentManager(this)
//
//        customerId = SessionManager.getCustomerId(this)
//        shopId = intent.getStringExtra("SHOP_ID") ?: SessionManager.getShopId(this)
//        shopName = SessionManager.getShopName(this) ?: "Shop"
//
//        if (customerId == null || shopId == null) {
//            Toast.makeText(this, "Session expired. Please login again.", Toast.LENGTH_SHORT).show()
//            startActivity(Intent(this, LoginActivity::class.java))
//            finish()
//            return
//        }
//
//        cartItems = intent.getParcelableArrayListExtra<CartItem>("cart")
//            ?: CartManager.getCart(shopId!!)
//
//        totalAmount = intent.getDoubleExtra("total", 0.0)
//
//        binding.textViewShopName.text = "Shop: $shopName"
//        binding.textViewTotal.text = "Total: ₹%.2f".format(totalAmount)
//
//        payNowAmount = totalAmount
//        dueAmount = 0.0
//
//        binding.editTextPayNow.setText("%.2f".format(payNowAmount))
//        binding.textViewDueAmount.text = "Due: ₹%.2f".format(dueAmount)
//
//        setupPayNowWatcher()
//        setupPaymentSelection()
//
//        binding.buttonPlaceOrder.setOnClickListener { handlePlaceOrder() }
//    }
//
//    /** PAY NOW TEXT LISTENER **/
//    private fun setupPayNowWatcher() {
//        binding.editTextPayNow.addTextChangedListener(object : TextWatcher {
//            override fun afterTextChanged(s: Editable?) {
//                val text = s?.toString()?.trim() ?: ""
//                payNowAmount = text.toDoubleOrNull() ?: 0.0
//
//                if (payNowAmount > totalAmount) {
//                    payNowAmount = totalAmount
//                    binding.editTextPayNow.setText("%.2f".format(totalAmount))
//                    binding.editTextPayNow.setSelection(binding.editTextPayNow.text.length)
//                }
//
//                dueAmount = totalAmount - payNowAmount
//                binding.textViewDueAmount.text = "Due: ₹%.2f".format(dueAmount)
//
//                // RED IF DUE
//                if (dueAmount > 0) {
//                    binding.textViewDueAmount.setTextColor(
//                        ContextCompat.getColor(this@OrderConfirmActivity, android.R.color.holo_red_dark)
//                    )
//                } else {
//                    binding.textViewDueAmount.setTextColor(
//                        ContextCompat.getColor(this@OrderConfirmActivity, android.R.color.black)
//                    )
//                }
//            }
//
//            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
//            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
//        })
//    }
//
//    /** PAYMENT OPTION SELECTION **/
//    private fun setupPaymentSelection() {
//        highlight("UPI")
//
//        binding.optionUpi.setOnClickListener {
//            selectedPaymentLabel = "UPI"
//            highlight("UPI")
//        }
//
//        binding.optionWallet.setOnClickListener {
//            if (walletBalance < payNowAmount) {
//                Toast.makeText(this, "Insufficient wallet balance!", Toast.LENGTH_SHORT).show()
//                return@setOnClickListener
//            }
//            selectedPaymentLabel = "Wallet"
//            highlight("Wallet")
//        }
//
//        binding.btnCheckWallet.setOnClickListener { fetchWalletBalance() }
//
//        binding.optionCash.setOnClickListener {
//            selectedPaymentLabel = "Cash"
//            highlight("Cash")
//        }
//    }
//
//    private fun highlight(selected: String) {
//        binding.optionUpi.setBackgroundResource(R.drawable.payment_option_bg)
//        binding.optionWallet.setBackgroundResource(R.drawable.payment_option_bg)
//        binding.optionCash.setBackgroundResource(R.drawable.payment_option_bg)
//
//        when (selected) {
//            "UPI" -> binding.optionUpi.setBackgroundResource(R.drawable.payment_option_selected)
//            "Wallet" -> binding.optionWallet.setBackgroundResource(R.drawable.payment_option_selected)
//            "Cash" -> binding.optionCash.setBackgroundResource(R.drawable.payment_option_selected)
//        }
//    }
//
//    /** API CALL FOR WALLET BALANCE **/
//    private fun fetchWalletBalance() {
//        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
//        api.getWalletBalance(customerId!!).enqueue(object : Callback<WalletBalanceResponse> {
//            override fun onResponse(call: Call<WalletBalanceResponse>, response: Response<WalletBalanceResponse>) {
//                if (response.isSuccessful) {
//
//                    walletBalance = response.body()?.balance ?: 0.0
//
//                    // SHOW BALANCE & REMOVE BUTTON
//                    binding.txtWalletBalance.text = "Balance: ₹$walletBalance"
//                    binding.txtWalletBalance.visibility = View.VISIBLE
//                    binding.btnCheckWallet.visibility = View.GONE
//
//                    Toast.makeText(this@OrderConfirmActivity, "Wallet: ₹$walletBalance", Toast.LENGTH_SHORT).show()
//
//                } else {
//                    Toast.makeText(this@OrderConfirmActivity, "Failed to fetch balance", Toast.LENGTH_SHORT).show()
//                }
//            }
//
//            override fun onFailure(call: Call<WalletBalanceResponse>, t: Throwable) {
//                Toast.makeText(this@OrderConfirmActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
//            }
//        })
//    }
//
//    private fun handlePlaceOrder() {
//        val backendPaymentMethod = when (selectedPaymentLabel) {
//            "UPI" -> "Razorpay"
//            "Wallet" -> "Wallet"
//            else -> "Cash"
//        }
//
//        orderManager.placeOrder(
//            cartItems = cartItems,
//            shopId = shopId!!,
//            paymentMethod = backendPaymentMethod,
//            transactionId = "",
//            payNowAmount = payNowAmount,
//            dueAmount = dueAmount
//        )
//    }
//
//    fun onOrderPlacedSuccess(orderId: String?, razorpayOrderId: String?, method: String) {
//        backendOrderId = orderId
//        this.razorpayOrderId = razorpayOrderId
//
//        when (method) {
//            "Razorpay" -> paymentManager.startRazorpayCheckout(shopName, payNowAmount, razorpayOrderId)
//            "Wallet" -> {
//                Toast.makeText(this, "Paid using Wallet!", Toast.LENGTH_SHORT).show()
//                CartManager.clearCart(shopId!!)
//                goToThankYou()
//            }
//            else -> {
//                Toast.makeText(this, "Cash Order Placed!", Toast.LENGTH_SHORT).show()
//                CartManager.clearCart(shopId!!)
//                goToThankYou()
//            }
//        }
//    }
//
//    override fun onPaymentSuccess(paymentId: String?, data: PaymentData?) {
//        paymentManager.verifyPayment(backendOrderId, paymentId, data?.orderId, data?.signature)
//    }
//
//    override fun onPaymentError(code: Int, response: String?, data: PaymentData?) {
//        Toast.makeText(this, "Payment Failed!", Toast.LENGTH_SHORT).show()
//    }
//
//    fun onPaymentVerified() {
//        Toast.makeText(this, "Payment Verified!", Toast.LENGTH_SHORT).show()
//        CartManager.clearCart(shopId!!)
//        goToThankYou()
//    }
//
//    private fun goToThankYou() {
//        startActivity(Intent(this, ThankYouActivity::class.java))
//        finish()
//    }
//
//    fun onOrderPlacedError(message: String) {
//        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
//    }
//}
package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.example.groceryshoppingapp.databinding.ActivityOrderConfirmBinding
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.models.WalletBalanceResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import com.razorpay.Checkout
import com.razorpay.PaymentData
import com.razorpay.PaymentResultWithDataListener
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class OrderConfirmActivity : AppCompatActivity(), PaymentResultWithDataListener {

    private lateinit var binding: ActivityOrderConfirmBinding

    private lateinit var cartItems: List<CartItem>
    private var totalAmount = 0.0
    private var payNowAmount = 0.0
    private var dueAmount = 0.0

    private var customerId: String? = null
    private var shopId: String? = null
    private var shopName = "Shop"

    private var selectedPaymentLabel = "UPI"
    private var walletBalance = 0.0

    private lateinit var orderManager: OrderManager
    private lateinit var paymentManager: PaymentManager

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

        if (customerId == null || shopId == null) {
            Toast.makeText(this, "Session expired. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        cartItems = intent.getParcelableArrayListExtra<CartItem>("cart")
            ?: CartManager.getCart(shopId!!)

        totalAmount = intent.getDoubleExtra("total", 0.0)

        binding.textViewShopName.text = "Shop: $shopName"
        binding.textViewTotal.text = "Total: ₹%.2f".format(totalAmount)

        payNowAmount = totalAmount
        dueAmount = 0.0

        binding.editTextPayNow.setText("%.2f".format(payNowAmount))
        binding.textViewDueAmount.text = "Due: ₹%.2f".format(dueAmount)

        setupPayNowWatcher()
        setupPaymentSelection()

        binding.buttonPlaceOrder.setOnClickListener { handlePlaceOrder() }
    }

    /** PAY NOW TEXT LISTENER **/
    private fun setupPayNowWatcher() {
        binding.editTextPayNow.addTextChangedListener(object : TextWatcher {
            override fun afterTextChanged(s: Editable?) {
                val text = s?.toString()?.trim() ?: ""
                payNowAmount = text.toDoubleOrNull() ?: 0.0

                if (payNowAmount > totalAmount) {
                    payNowAmount = totalAmount
                    binding.editTextPayNow.setText("%.2f".format(totalAmount))
                    binding.editTextPayNow.setSelection(binding.editTextPayNow.text.length)
                }

                dueAmount = totalAmount - payNowAmount
                binding.textViewDueAmount.text = "Due: ₹%.2f".format(dueAmount)

                // RED IF DUE
                if (dueAmount > 0) {
                    binding.textViewDueAmount.setTextColor(
                        ContextCompat.getColor(this@OrderConfirmActivity, android.R.color.holo_red_dark)
                    )
                } else {
                    binding.textViewDueAmount.setTextColor(
                        ContextCompat.getColor(this@OrderConfirmActivity, android.R.color.black)
                    )
                }

                // If wallet was previously selected, recheck balance logic
                if (selectedPaymentLabel == "Wallet") {
                    if (walletBalance < payNowAmount) {
                        binding.txtWalletError.text = "Insufficient Balance!"
                        binding.txtWalletError.visibility = View.VISIBLE
                    } else {
                        binding.txtWalletError.visibility = View.GONE
                    }
                }
            }

            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
        })
    }

    /** PAYMENT OPTION SELECTION **/
    private fun setupPaymentSelection() {
        highlight("UPI")

        binding.optionUpi.setOnClickListener {
            selectedPaymentLabel = "UPI"
            highlight("UPI")
            binding.txtWalletError.visibility = View.GONE
        }

        binding.optionWallet.setOnClickListener {
            if (walletBalance < payNowAmount) {
                binding.txtWalletError.text = "Insufficient Balance!"
                binding.txtWalletError.visibility = View.VISIBLE
                return@setOnClickListener
            }

            binding.txtWalletError.visibility = View.GONE
            selectedPaymentLabel = "Wallet"
            highlight("Wallet")
        }

        binding.btnCheckWallet.setOnClickListener { fetchWalletBalance() }

        binding.optionCash.setOnClickListener {
            selectedPaymentLabel = "Cash"
            highlight("Cash")
            binding.txtWalletError.visibility = View.GONE
        }
    }

    private fun highlight(selected: String) {
        binding.optionUpi.setBackgroundResource(R.drawable.payment_option_bg)
        binding.optionWallet.setBackgroundResource(R.drawable.payment_option_bg)
        binding.optionCash.setBackgroundResource(R.drawable.payment_option_bg)

        when (selected) {
            "UPI" -> binding.optionUpi.setBackgroundResource(R.drawable.payment_option_selected)
            "Wallet" -> binding.optionWallet.setBackgroundResource(R.drawable.payment_option_selected)
            "Cash" -> binding.optionCash.setBackgroundResource(R.drawable.payment_option_selected)
        }
    }

    /** API CALL FOR WALLET BALANCE **/
    private fun fetchWalletBalance() {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.getWalletBalance(customerId!!).enqueue(object : Callback<WalletBalanceResponse> {
            override fun onResponse(call: Call<WalletBalanceResponse>, response: Response<WalletBalanceResponse>) {
                if (response.isSuccessful) {

                    walletBalance = response.body()?.balance ?: 0.0

                    // SHOW BALANCE IN BOLD BLACK
                    binding.txtWalletBalance.text = "Balance: ₹$walletBalance"
                    binding.txtWalletBalance.visibility = View.VISIBLE
                    binding.txtWalletBalance.setTextColor(ContextCompat.getColor(this@OrderConfirmActivity, android.R.color.black))
                    binding.txtWalletBalance.textSize = 16F

                    binding.txtWalletError.visibility = View.GONE
                    binding.btnCheckWallet.visibility = View.GONE

                } else {
                    Toast.makeText(this@OrderConfirmActivity, "Failed to fetch balance", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<WalletBalanceResponse>, t: Throwable) {
                Toast.makeText(this@OrderConfirmActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun handlePlaceOrder() {
        val backendPaymentMethod = when (selectedPaymentLabel) {
            "UPI" -> "Razorpay"
            "Wallet" -> "Wallet"
            else -> "Cash"
        }

        orderManager.placeOrder(
            cartItems = cartItems,
            shopId = shopId!!,
            paymentMethod = backendPaymentMethod,
            transactionId = "",
            payNowAmount = payNowAmount,
            dueAmount = dueAmount
        )
    }

    fun onOrderPlacedSuccess(orderId: String?, razorpayOrderId: String?, method: String) {
        backendOrderId = orderId
        this.razorpayOrderId = razorpayOrderId

        when (method) {
            "Razorpay" -> paymentManager.startRazorpayCheckout(shopName, payNowAmount, razorpayOrderId)
            "Wallet" -> {
                CartManager.clearCart(shopId!!)
                Toast.makeText(this, "Paid using Wallet!", Toast.LENGTH_SHORT).show()
                goToThankYou()
            }
            else -> {
                CartManager.clearCart(shopId!!)
                Toast.makeText(this, "Cash Order Placed!", Toast.LENGTH_SHORT).show()
                goToThankYou()
            }
        }
    }

    override fun onPaymentSuccess(paymentId: String?, data: PaymentData?) {
        paymentManager.verifyPayment(backendOrderId, paymentId, data?.orderId, data?.signature)
    }

    override fun onPaymentError(code: Int, response: String?, data: PaymentData?) {
        Toast.makeText(this, "Payment Failed!", Toast.LENGTH_SHORT).show()
    }

    fun onPaymentVerified() {
        CartManager.clearCart(shopId!!)
        Toast.makeText(this, "Payment Verified!", Toast.LENGTH_SHORT).show()
        goToThankYou()
    }

    private fun goToThankYou() {
        startActivity(Intent(this, ThankYouActivity::class.java))
        finish()
    }

    fun onOrderPlacedError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }
}

