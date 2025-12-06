package com.example.groceryshoppingapp

import android.annotation.SuppressLint
import android.graphics.Color
import android.content.Intent
import android.os.Bundle
import android.text.SpannableString
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.widget.addTextChangedListener
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.adapters.KhataAccountAdapter
import com.example.groceryshoppingapp.databinding.ActivityCustomerKhataListBinding
import com.example.groceryshoppingapp.models.KhataAccount
import com.example.groceryshoppingapp.models.KhataAccountsResponse
import com.example.groceryshoppingapp.models.WalletBalanceResponse
import com.example.groceryshoppingapp.network.ApiResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.CashPaymentRequest
import com.example.groceryshoppingapp.network.KhataRazorpayOrderRequest
import com.example.groceryshoppingapp.network.KhataRazorpayOrderResponse
import com.example.groceryshoppingapp.network.KhataRazorpayVerifyRequest
import com.example.groceryshoppingapp.network.PayKhataRequest
import com.example.groceryshoppingapp.network.PayKhataResponse
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.firebase.firestore.ktx.firestore
import com.google.firebase.ktx.Firebase
import com.razorpay.Checkout
import com.razorpay.PaymentData
import com.razorpay.PaymentResultWithDataListener
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.*

class CustomerKhataListActivity : AppCompatActivity(), PaymentResultWithDataListener {

    private lateinit var binding: ActivityCustomerKhataListBinding
    private lateinit var api: ApiService
    private val accounts = mutableListOf<KhataAccount>()
    private lateinit var adapter: KhataAccountAdapter

    // ⭐ For UPI / Razorpay khata payments
    private var khataBackendOrderId: String? = null
    private var khataPayAmount: Double = 0.0
    private var khataPayAccount: KhataAccount? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityCustomerKhataListBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Razorpay preload
        Checkout.preload(applicationContext)

        api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        binding.rvKhataList.layoutManager = LinearLayoutManager(this)

        adapter = KhataAccountAdapter(
            accounts,
            onViewClick = { acc ->
                val intent = Intent(this, KhataCustomerDetailActivity::class.java)
                intent.putExtra("account", acc)
                intent.putExtra("isReadOnly", true)
                startActivity(intent)
            },
            onPayClick = { acc ->
                showPaymentMethodDialog(acc)
            }
        )

        binding.rvKhataList.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.swipeRefresh.setOnRefreshListener { loadAccounts() }

        loadAccounts()
        listenRealtime()
    }

    // ----------------- LOAD ACCOUNTS -----------------

    private fun loadAccounts() {
        val customerId = SessionManager.getCustomerId(this) ?: return
        binding.swipeRefresh.isRefreshing = true

        api.getMyKhataAccounts(customerId)
            .enqueue(object : Callback<KhataAccountsResponse> {
                override fun onResponse(
                    call: Call<KhataAccountsResponse>,
                    response: Response<KhataAccountsResponse>
                ) {
                    binding.swipeRefresh.isRefreshing = false

                    accounts.clear()
                    response.body()?.accounts?.forEach { acc ->
                        acc.shopName = acc.shopName ?: "Unknown Shop"
                        accounts.add(acc)
                    }

                    adapter.notifyDataSetChanged()
                    updateLastUpdated()
                }

                override fun onFailure(call: Call<KhataAccountsResponse>, t: Throwable) {
                    binding.swipeRefresh.isRefreshing = false
                    Toast.makeText(
                        this@CustomerKhataListActivity,
                        t.message,
                        Toast.LENGTH_SHORT
                    ).show()
                }
            })
    }

    private fun updateLastUpdated() {
        val sdf = SimpleDateFormat("hh:mm a", Locale.getDefault())
        binding.tvLastUpdated.text = "Updated: ${sdf.format(Date())}"
    }

    // Firestore realtime listener for account list
    private fun listenRealtime() {
        val customerId = SessionManager.getCustomerId(this) ?: return

        Firebase.firestore.collection("khata_accounts")
            .whereEqualTo("customer_id", customerId)
            .addSnapshotListener { snap, _ ->
                if (snap == null) return@addSnapshotListener

                accounts.clear()
                snap.documents.forEach { doc ->
                    val acc = doc.toObject(KhataAccount::class.java) ?: return@forEach

                    acc.shopName = doc.getString("shop_name") ?: acc.shopName
                    acc.shopId = doc.getString("shop_id") ?: acc.shopId

                    // pending fields
                    acc.pendingCash = doc.getDouble("pending_cash")
                    acc.pendingStatus = doc.getString("pending_status")
                    acc.pendingRequestId = doc.getString("pending_request_id")

                    accounts.add(acc)
                }

                adapter.notifyDataSetChanged()
                updateLastUpdated()
            }
    }

    // ----------------- WALLET BALANCE -----------------

    private fun fetchWalletBalance(callback: (Double) -> Unit) {
        val userId = SessionManager.getCustomerId(this) ?: return

        api.getWalletBalance(userId)
            .enqueue(object : Callback<WalletBalanceResponse> {
                override fun onResponse(
                    call: Call<WalletBalanceResponse>,
                    response: Response<WalletBalanceResponse>
                ) {
                    val balance = response.body()?.balance ?: 0.0
                    SessionManager.saveWalletBalance(this@CustomerKhataListActivity, balance)
                    callback(balance)
                }

                override fun onFailure(call: Call<WalletBalanceResponse>, t: Throwable) {
                    callback(0.0)
                }
            })
    }

    // ----------------- PAYMENT METHOD DIALOG -----------------

    private fun showPaymentMethodDialog(acc: KhataAccount) {

        // Block if there's a pending cash request
        if (acc.pendingStatus == "pending") {
            Toast.makeText(
                this,
                "Cash payment request pending approval",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        // Now 3 options: Wallet, Cash, UPI/Razorpay
        val options = arrayOf("Wallet", "Cash Payment", "UPI / Razorpay")

        AlertDialog.Builder(this)
            .setTitle("Choose Payment Method")
            .setItems(options) { _, which ->
                when (which) {
                    0 -> fetchWalletBalance { balance ->
                        showWalletConfirmation(acc, balance)
                    }

                    1 -> showCashAmountDialog(acc)
                    2 -> showUpiAmountDialog(acc)   // ⭐ NEW
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ----------------- CASH PAYMENT -----------------

    private fun showCashAmountDialog(acc: KhataAccount) {

        val input = EditText(this)
        input.hint = "Enter cash amount"
        input.inputType = android.text.InputType.TYPE_CLASS_NUMBER

        AlertDialog.Builder(this)
            .setTitle("Cash Payment to ${acc.shopName}")
            .setMessage("Enter amount to pay in cash")
            .setView(input)
            .setPositiveButton("Submit") { _, _ ->
                val amount = input.text.toString().toDoubleOrNull() ?: 0.0
                if (amount <= 0) {
                    Toast.makeText(this, "Invalid amount", Toast.LENGTH_SHORT).show()
                } else {
                    sendCashPaymentRequest(acc, amount)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun sendCashPaymentRequest(acc: KhataAccount, amount: Double) {

        val request = CashPaymentRequest(
            customer_id = SessionManager.getCustomerId(this) ?: "",
            shop_id = acc.shopId ?: "",
            amount = amount
        )

        api.createCashPaymentRequest(request)
            .enqueue(object : Callback<ApiResponse> {
                override fun onResponse(
                    call: Call<ApiResponse>,
                    response: Response<ApiResponse>
                ) {
                    if (response.isSuccessful && response.body()?.success == true) {
                        Toast.makeText(
                            this@CustomerKhataListActivity,
                            "Cash payment request sent to shop owner",
                            Toast.LENGTH_LONG
                        ).show()
                    } else {
                        Toast.makeText(
                            this@CustomerKhataListActivity,
                            response.body()?.message ?: "Failed",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }

                override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
                    Toast.makeText(
                        this@CustomerKhataListActivity,
                        t.message,
                        Toast.LENGTH_LONG
                    ).show()
                }
            })
    }

    // ----------------- WALLET FLOW -----------------
    @SuppressLint("SetTextI18n")
    private fun showWalletConfirmation(acc: KhataAccount, walletBalance: Double) {

        val amountDue = acc.balance ?: 0.0

        val dialog = AlertDialog.Builder(this)
            .setTitle("Confirm Wallet Payment")
            .setMessage("") // we will set dynamically
            .setPositiveButton("Yes", null)
            .setNegativeButton("No", null)
            .create()

        dialog.setOnShowListener {

            val btnYes = dialog.getButton(AlertDialog.BUTTON_POSITIVE)

            // Get reference to AlertDialog message TextView
            val tvMsg = dialog.findViewById<TextView>(android.R.id.message)

            when {
                // 🔥 Case 1: Wallet Balance = 0 → No payment possible
                walletBalance == 0.0 -> {

                    val line1 = "Wallet Balance: ₹$walletBalance\n"
                    val line2 = "Amount to Pay: ₹$amountDue\n\n"
                    val line3 = "❌ Wallet Balance is 0. Please add money."

                    val fullText = line1 + line2 + line3
                    val spannable = SpannableString(fullText)

                    // 🔴 Make line1 (Wallet Balance) RED
                    spannable.setSpan(
                        ForegroundColorSpan(Color.RED),
                        0,
                        line1.length,
                        Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                    )

                    // 🔴 Make last line (Error message) RED
                    val startLine3 = fullText.indexOf(line3)
                    val endLine3 = fullText.length
                    spannable.setSpan(
                        ForegroundColorSpan(Color.RED),
                        startLine3,
                        endLine3,
                        Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                    )

                    tvMsg?.text = spannable

                    btnYes.isEnabled = false
                    btnYes.setTextColor(Color.GRAY)
                }

                // 🔥 Case 2: Wallet is less than due → partial payment allowed
                walletBalance < amountDue -> {

                    val line1 = "Wallet Balance: ₹$walletBalance\n"
                    val line2 = "Amount to Pay: ₹$amountDue\n\n"
                    val line3 = "⚠️ Insufficient Wallet Balance\n\n"
                    val line4 = "You can still enter a partial amount."

                    val full = line1 + line2 + line3 + line4
                    val span = SpannableString(full)

                    // 🎨 Colors
                    val darkOrange = Color.parseColor("#EF6C00")   // line1
                    val darkRed = Color.parseColor("#C62828")      // line3
                    //val blue = Color.parseColor("#1565C0")         // line4 (or switch to green)
                    val green = Color.parseColor("#2E7D32")     // if you prefer green

                    // 🟧 Line 1 — dark orange
                    span.setSpan(
                        ForegroundColorSpan(darkOrange),
                        0,
                        line1.length,
                        Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                    )

                    // ⚫ Line 2 stays black (no span)

                    // 🔴 Line 3 — dark red
                    val start3 = full.indexOf(line3)
                    span.setSpan(
                        ForegroundColorSpan(darkRed),
                        start3,
                        start3 + line3.length,
                        Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                    )

                    // 🔵 Line 4 — blue (or green)
                    val start4 = full.indexOf(line4)
                    span.setSpan(
                        ForegroundColorSpan(green),
                        start4,
                        full.length,
                        Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                    )

                    tvMsg?.text = span

                    btnYes.isEnabled = true
                    btnYes.setOnClickListener {
                        dialog.dismiss()
                        showAmountInputDialog(acc)
                    }
                }



                // 🔥 Case 3: Wallet >= due → full or partial allowed
                else -> {
                    tvMsg?.text =
                        "Wallet Balance: ₹$walletBalance\n" +
                                "Amount to Pay: ₹$amountDue\n\n" +
                                "Do you want to continue?"

                    tvMsg?.setTextColor(Color.BLACK)

                    btnYes.isEnabled = true
                    btnYes.setOnClickListener {
                        dialog.dismiss()
                        showAmountInputDialog(acc)
                    }
                }
            }
        }

        dialog.show()
    }


    private fun showAmountInputDialog(acc: KhataAccount) {

        val walletBalance = SessionManager.getWalletBalance(this)
        val amountDue = acc.balance ?: 0.0

        val input = EditText(this)
        input.hint = "Enter amount"
        input.inputType = android.text.InputType.TYPE_CLASS_NUMBER

        // Red warning text
        val warning = TextView(this)
        warning.setTextColor(Color.RED)
        warning.textSize = 13f
        warning.text = ""

        val layout = LinearLayout(this)
        layout.orientation = LinearLayout.VERTICAL
        layout.setPadding(50, 20, 50, 0)
        layout.addView(input)
        layout.addView(warning)

        val dialog = AlertDialog.Builder(this)
            .setTitle("Pay Due • ${acc.shopName}")
            .setMessage("Due: ₹$amountDue\nWallet: ₹$walletBalance")
            .setView(layout)
            .setPositiveButton("Pay", null)
            .setNegativeButton("Cancel", null)
            .create()

        dialog.setOnShowListener {
            val btnPay = dialog.getButton(AlertDialog.BUTTON_POSITIVE)

            // Disable initially until valid input
            btnPay.isEnabled = false

            btnPay.setOnClickListener {
                val amount = input.text.toString().toDoubleOrNull() ?: 0.0

                if (amount > walletBalance) {
                    warning.text = "Insufficient wallet balance (Available: ₹$walletBalance)"
                    return@setOnClickListener
                }

                if (amount <= 0) {
                    warning.text = "Enter valid amount"
                    return@setOnClickListener
                }

                dialog.dismiss()
                payKhata(acc, amount)
            }

            // Live validation
            input.addTextChangedListener {
                val amount = it.toString().toDoubleOrNull() ?: 0.0

                when {
                    amount > walletBalance -> {
                        warning.text =
                            "Insufficient wallet balance (Available: ₹$walletBalance)"
                        btnPay.isEnabled = false
                    }

                    amount <= 0 -> {
                        warning.text = "Enter valid amount"
                        btnPay.isEnabled = false
                    }

                    else -> {
                        warning.text = ""
                        btnPay.isEnabled = true
                    }
                }
            }
        }

        dialog.show()
    }

    private fun payKhata(acc: KhataAccount, amount: Double) {

        val request = PayKhataRequest(
            shop_id = acc.shopId ?: "",
            customer_id = SessionManager.getCustomerId(this) ?: "",
            amount = amount
        )

        api.payKhataFromWallet(request)
            .enqueue(object : Callback<PayKhataResponse> {

                override fun onResponse(
                    call: Call<PayKhataResponse>,
                    response: Response<PayKhataResponse>
                ) {
                    val body = response.body() ?: return

                    if (body.success) {

                        SessionManager.saveWalletBalance(
                            this@CustomerKhataListActivity,
                            body.wallet_balance
                        )

                        AlertDialog.Builder(this@CustomerKhataListActivity)
                            .setTitle("Payment Successful")
                            .setMessage("Paid: ₹$amount\nNew Wallet Balance: ₹${body.wallet_balance}")
                            .setPositiveButton("OK", null)
                            .show()

                        loadAccounts()
                    } else {
                        Toast.makeText(
                            this@CustomerKhataListActivity,
                            body.message ?: "Error",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }

                override fun onFailure(call: Call<PayKhataResponse>, t: Throwable) {
                    Toast.makeText(
                        this@CustomerKhataListActivity,
                        t.message,
                        Toast.LENGTH_LONG
                    ).show()
                }
            })
    }

    // ----------------- UPI / RAZORPAY KHATA FLOW -----------------

    // Step 1: Ask amount
    private fun showUpiAmountDialog(acc: KhataAccount) {
        val input = EditText(this)
        input.hint = "Enter amount"
        input.inputType = android.text.InputType.TYPE_CLASS_NUMBER

        AlertDialog.Builder(this)
            .setTitle("Pay Using UPI • ${acc.shopName}")
            .setMessage("Your due: ₹${acc.balance}")
            .setView(input)
            .setPositiveButton("Pay") { _, _ ->
                val amount = input.text.toString().toDoubleOrNull() ?: 0.0
                if (amount > 0) {
                    createKhataRazorpayOrder(acc, amount)
                } else {
                    Toast.makeText(this, "Invalid amount", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // Step 2: Call backend to create Razorpay order for khata
    private fun createKhataRazorpayOrder(acc: KhataAccount, amount: Double) {

        val req = KhataRazorpayOrderRequest(
            customer_id = SessionManager.getCustomerId(this) ?: "",
            shop_id = acc.shopId ?: "",
            amount = amount
        )

        api.createKhataRazorpayOrder(req)
            .enqueue(object : Callback<KhataRazorpayOrderResponse> {

                override fun onResponse(
                    call: Call<KhataRazorpayOrderResponse>,
                    resp: Response<KhataRazorpayOrderResponse>
                ) {
                    val body = resp.body()
                    if (body?.success == true &&
                        !body.backend_order_id.isNullOrEmpty() &&
                        !body.razorpay_order_id.isNullOrEmpty()
                    ) {
                        khataBackendOrderId = body.backend_order_id
                        khataPayAmount = amount
                        khataPayAccount = acc
                        startKhataRazorpayPayment(amount, body.razorpay_order_id!!)
                    } else {
                        Toast.makeText(
                            this@CustomerKhataListActivity,
                            body?.message ?: "Error creating UPI order",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }

                override fun onFailure(
                    call: Call<KhataRazorpayOrderResponse>,
                    t: Throwable
                ) {
                    Toast.makeText(
                        this@CustomerKhataListActivity,
                        t.message,
                        Toast.LENGTH_LONG
                    ).show()
                }
            })
    }

    // Step 3: Open Razorpay Checkout
    private fun startKhataRazorpayPayment(amount: Double, razorpayOrderId: String) {

        val checkout = Checkout()
        // TODO: set your actual Razorpay Key ID
        checkout.setKeyID("rzp_test_RKK3DuGSaxK9fR")

        try {
            val options = JSONObject()
            options.put("name", khataPayAccount?.shopName ?: "Khata Payment")
            options.put("currency", "INR")
            options.put("amount", (amount * 100).toInt())
            options.put("order_id", razorpayOrderId)
            options.put("description", "Khata payment")

            checkout.open(this, options)
        } catch (e: Exception) {
            Toast.makeText(
                this,
                "Razorpay error: ${e.message}",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    // Step 4: Razorpay callbacks

    override fun onPaymentSuccess(paymentId: String?, data: PaymentData?) {
        // Only handle if it was a khata order from this screen
        val backendId = khataBackendOrderId ?: return

        val orderId = data?.orderId ?: ""
        val signature = data?.signature ?: ""

        if (paymentId.isNullOrEmpty() || orderId.isEmpty() || signature.isEmpty()) {
            Toast.makeText(this, "Missing payment data", Toast.LENGTH_SHORT).show()
            return
        }

        verifyKhataRazorpayPayment(
            backendOrderId = backendId,
            paymentId = paymentId,
            orderId = orderId,
            signature = signature
        )
    }

    override fun onPaymentError(code: Int, response: String?, data: PaymentData?) {
        Toast.makeText(
            this,
            "Payment failed: $response",
            Toast.LENGTH_LONG
        ).show()
    }

    // Step 5: Verify payment with backend & add khata transaction there
    private fun verifyKhataRazorpayPayment(
        backendOrderId: String,
        paymentId: String,
        orderId: String,
        signature: String
    ) {
        val req = KhataRazorpayVerifyRequest(
            backend_order_id = backendOrderId,
            order_id = orderId,
            payment_id = paymentId,
            signature = signature
        )

        api.verifyKhataRazorpayPayment(req)
            .enqueue(object : Callback<ApiResponse> {
                override fun onResponse(
                    call: Call<ApiResponse>,
                    resp: Response<ApiResponse>
                ) {
                    if (resp.body()?.success == true) {
                        AlertDialog.Builder(this@CustomerKhataListActivity)
                            .setTitle("Payment Successful")
                            .setMessage("Khata payment of ₹$khataPayAmount completed.")
                            .setPositiveButton("OK", null)
                            .show()

                        // Refresh khata list
                        loadAccounts()
                    } else {
                        Toast.makeText(
                            this@CustomerKhataListActivity,
                            resp.body()?.message ?: "Verification failed",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }

                override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
                    Toast.makeText(
                        this@CustomerKhataListActivity,
                        t.message,
                        Toast.LENGTH_LONG
                    ).show()
                }
            })
    }
}
