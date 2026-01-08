package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.util.Log
import android.view.animation.AnimationUtils
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

    private var selectedPaymentLabel = ""
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
                updateDueColor()

                if (selectedPaymentLabel == "Wallet") {
                    if (walletBalance < payNowAmount) {
                        showWalletError()
                    } else {
                        hideWalletError()
                    }
                }
            }

            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
        })
    }

    private fun updateDueColor() {
        binding.textViewDueAmount.text = "Due: ₹%.2f".format(dueAmount)

        binding.textViewDueAmount.setTextColor(
            if (dueAmount > 0)
                ContextCompat.getColor(this, android.R.color.holo_red_dark)
            else
                ContextCompat.getColor(this, android.R.color.black)
        )
    }

    /** PAYMENT OPTION SELECTION **/
    private fun setupPaymentSelection() {

        binding.optionUpi.setOnClickListener {
            selectPayment("UPI")
            enablePayNow()
        }

        binding.optionWallet.setOnClickListener {
            if (walletBalance < payNowAmount) {
                showWalletError()
                shakeView(binding.optionWallet)
                return@setOnClickListener
            }
            selectPayment("Wallet")
            enablePayNow()
            hideWalletError()
        }

        binding.btnCheckWallet.setOnClickListener { fetchWalletBalance() }

        binding.optionCash.setOnClickListener {
            selectPayment("Cash")
            enablePayNow()
        }

        binding.optionKhata.setOnClickListener {
            selectPayment("Khata")
            disablePayNow()
            binding.editTextPayNow.setText("0.00")

            dueAmount = totalAmount
            updateDueColor()
        }
    }

    private fun selectPayment(method: String) {

        selectedPaymentLabel = method

        // Hide all ticks
        binding.tickUpi.visibility = View.GONE
        binding.tickWallet.visibility = View.GONE
        binding.tickCash.visibility = View.GONE
        binding.tickKhata.visibility = View.GONE

        // Reset card selection
        binding.optionUpi.isSelected = false
        binding.optionWallet.isSelected = false
        binding.optionCash.isSelected = false
        binding.optionKhata.isSelected = false

        // Animate tick fade-in
        fun showTick(view: View) {
            view.visibility = View.VISIBLE
            view.alpha = 0f
            view.animate().alpha(1f).setDuration(150).start()
        }

        when (method) {
            "UPI" -> {
                binding.optionUpi.isSelected = true
                showTick(binding.tickUpi)
            }
            "Wallet" -> {
                binding.optionWallet.isSelected = true
                showTick(binding.tickWallet)
            }
            "Cash" -> {
                binding.optionCash.isSelected = true
                showTick(binding.tickCash)
            }
            "Khata" -> {
                binding.optionKhata.isSelected = true
                showTick(binding.tickKhata)
            }
        }
    }

    private fun enablePayNow() {
        binding.editTextPayNow.isEnabled = true
    }

    private fun disablePayNow() {
        binding.editTextPayNow.isEnabled = false
    }

    private fun showWalletError() {
        binding.txtWalletError.visibility = View.VISIBLE
        shakeView(binding.optionWallet)
    }

    private fun hideWalletError() {
        binding.txtWalletError.visibility = View.GONE
    }

    private fun shakeView(view: View) {
        val shake = AnimationUtils.loadAnimation(this, R.anim.shake_anim)
        view.startAnimation(shake)
    }

    /** API CALL FOR WALLET BALANCE **/
    private fun fetchWalletBalance() {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.getWalletBalance(customerId!!).enqueue(object : Callback<WalletBalanceResponse> {
            override fun onResponse(call: Call<WalletBalanceResponse>, response: Response<WalletBalanceResponse>) {
                if (response.isSuccessful) {

                    walletBalance = response.body()?.balance ?: 0.0

                    binding.txtWalletBalance.text = "Balance: ₹$walletBalance"
                    binding.txtWalletBalance.visibility = View.VISIBLE
                    hideWalletError()
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
        if (selectedPaymentLabel.isEmpty()) {
            Toast.makeText(this, "Please select a payment method", Toast.LENGTH_SHORT).show()
            return
        }

        val backendPaymentMethod = when (selectedPaymentLabel) {
            "UPI" -> "Razorpay"
            "Wallet" -> "Wallet"
            "Cash" -> "Cash"
            "Khata" -> "Khata"
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

            "Razorpay" -> {
                paymentManager.startRazorpayCheckout(
                    shopName,
                    payNowAmount,
                    razorpayOrderId
                )
            }

            "Wallet" -> {
                CartManager.clearCart(shopId!!)
                Toast.makeText(this, "Paid using Wallet!", Toast.LENGTH_SHORT).show()
                goToThankYou()
            }

            "Cash" -> {
                CartManager.clearCart(shopId!!)
                Toast.makeText(this, "Cash Order Placed!", Toast.LENGTH_SHORT).show()
                goToThankYou()
            }

            "Khata" -> {
                CartManager.clearCart(shopId!!)
                Toast.makeText(this, "Khata Order Added!", Toast.LENGTH_SHORT).show()
                goToThankYou()
            }
        }
    }

//    override fun onPaymentSuccess(paymentId: String?, data: PaymentData?) {
//        paymentManager.verifyPayment(backendOrderId, paymentId, data?.orderId, data?.signature)
//    }

    override fun onPaymentSuccess(paymentId: String?, data: PaymentData?) {

        Log.e("RAZORPAY", "paymentId=$paymentId")
        Log.e("RAZORPAY", "orderId=${data?.orderId}")
        Log.e("RAZORPAY", "signature=${data?.signature}")

        // ✅ IMPORTANT FIX: fallback to backend Razorpay orderId
        val finalOrderId = data?.orderId ?: razorpayOrderId
        val finalSignature = data?.signature

        if (paymentId.isNullOrBlank() ||
            finalOrderId.isNullOrBlank() ||
            finalSignature.isNullOrBlank()
        ) {
            Toast.makeText(this, "Payment verification failed. Retry.", Toast.LENGTH_LONG).show()
            return
        }

        paymentManager.verifyPayment(
            backendOrderId = backendOrderId,
            paymentId = paymentId,
            rpOrderId = finalOrderId,
            rpSignature = finalSignature
        )
    }



    override fun onPaymentError(code: Int, response: String?, data: PaymentData?) {
        Toast.makeText(this, "Payment Failed!", Toast.LENGTH_SHORT).show()
    }

    fun onPaymentVerified() {
        CartManager.clearCart(shopId!!)
        goToThankYou()
    }

    private fun goToThankYou() {

        val thankYouIntent = Intent(this, ThankYouActivity::class.java)

        thankYouIntent.putExtra("shop_id", shopId)           // ✅ FIXED
        thankYouIntent.putExtra("order_id", backendOrderId) // optional but recommended

        startActivity(thankYouIntent)
        finish()
    }


    fun onOrderPlacedError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }
}
