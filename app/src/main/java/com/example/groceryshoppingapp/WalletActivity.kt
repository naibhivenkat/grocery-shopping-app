//package com.example.groceryshoppingapp
//
//import android.os.Bundle
//import android.widget.Button
//import android.widget.TextView
//import android.widget.Toast
//import androidx.appcompat.app.AppCompatActivity
//import androidx.recyclerview.widget.LinearLayoutManager
//import androidx.recyclerview.widget.RecyclerView
//import com.example.groceryshoppingapp.adapters.WalletTransactionAdapter
//import com.example.groceryshoppingapp.models.WalletActionRequest
//import com.example.groceryshoppingapp.models.WalletActionResponse
//import com.example.groceryshoppingapp.models.WalletBalanceResponse
//import com.example.groceryshoppingapp.models.WalletTransaction
//import com.example.groceryshoppingapp.network.ApiService
//import com.example.groceryshoppingapp.network.RetrofitClient
//import com.example.groceryshoppingapp.utils.SessionManager
//import retrofit2.Call
//import retrofit2.Callback
//import retrofit2.Response
//
//class WalletActivity : AppCompatActivity() {
//
//    private lateinit var tvBalance: TextView
//    private lateinit var rvTransactions: RecyclerView
//    private lateinit var btnAddMoney: Button
//    private val transactions = mutableListOf<WalletTransaction>()
//    private lateinit var adapter: WalletTransactionAdapter
//
//    private lateinit var api: ApiService
//    private var userId: String? = null // ⚠ move initialization to onCreate
//
//    override fun onCreate(savedInstanceState: Bundle?) {
//        super.onCreate(savedInstanceState)
//        setContentView(R.layout.activity_wallet)
//
//        // ⚡ Initialize userId here
//        userId = SessionManager.getFirebaseId(this)
//
//
//        tvBalance = findViewById(R.id.tvBalance)
//        rvTransactions = findViewById(R.id.rvTransactions)
//        btnAddMoney = findViewById(R.id.btnAddMoney)
//
//        adapter = WalletTransactionAdapter(transactions)
//        rvTransactions.layoutManager = LinearLayoutManager(this)
//        rvTransactions.adapter = adapter
//
//        api = RetrofitClient.getInstance(this).create(ApiService::class.java)
//
//        fetchWalletBalance()
//        fetchTransactions()
//
//        btnAddMoney.setOnClickListener {
//            // Replace 100.0 with user input amount
//            addMoney(100.0)
//        }
//    }
//
//    private fun fetchWalletBalance() {
//        if (userId != null) {
//            api.getWalletBalance(userId!!).enqueue(object : Callback<WalletBalanceResponse> {
//                override fun onResponse(
//                    call: Call<WalletBalanceResponse>,
//                    response: Response<WalletBalanceResponse>
//                ) {
//                    if (response.isSuccessful) {
//                        val balance = response.body()?.balance ?: 0.0
//                        tvBalance.text = "Wallet Balance: ₹$balance"
//                    } else {
//                        Toast.makeText(this@WalletActivity, "Failed to fetch balance", Toast.LENGTH_SHORT).show()
//                    }
//                }
//
//                override fun onFailure(call: Call<WalletBalanceResponse>, t: Throwable) {
//                    t.printStackTrace()
//                    Toast.makeText(this@WalletActivity, "Error fetching balance", Toast.LENGTH_SHORT).show()
//                }
//            })
//        }
//    }
//
//    private fun fetchTransactions() {
//        if (userId != null) {
//            api.getWalletTransactions(userId!!).enqueue(object : Callback<List<WalletTransaction>> {
//                override fun onResponse(
//                    call: Call<List<WalletTransaction>>,
//                    response: Response<List<WalletTransaction>>
//                ) {
//                    if (response.isSuccessful) {
//                        transactions.clear()
//                        response.body()?.let { transactions.addAll(it) }
//                        adapter.notifyDataSetChanged()
//                    }
//                }
//
//                override fun onFailure(call: Call<List<WalletTransaction>>, t: Throwable) {
//                    t.printStackTrace()
//                    Toast.makeText(this@WalletActivity, "Error fetching transactions", Toast.LENGTH_SHORT).show()
//                }
//            })
//        }
//    }
//
//    private fun addMoney(amount: Double) {
//        val request = userId?.let { WalletActionRequest(user_id = it, amount = amount) }
//        if (request != null) {
//            api.addMoney(request).enqueue(object : Callback<WalletActionResponse> {
//                override fun onResponse(
//                    call: Call<WalletActionResponse>,
//                    response: Response<WalletActionResponse>
//                ) {
//                    if (response.isSuccessful) {
//                        val newBalance = response.body()?.balance ?: 0.0
//                        tvBalance.text = "Wallet Balance: ₹$newBalance"
//                        fetchTransactions()
//                        Toast.makeText(this@WalletActivity, "Money added successfully", Toast.LENGTH_SHORT).show()
//                    } else {
//                        Toast.makeText(this@WalletActivity, "Failed to add money", Toast.LENGTH_SHORT).show()
//                    }
//                }
//
//                override fun onFailure(call: Call<WalletActionResponse>, t: Throwable) {
//                    t.printStackTrace()
//                    Toast.makeText(this@WalletActivity, "Error adding money", Toast.LENGTH_SHORT).show()
//                }
//            })
//        }
//    }
//
//    fun payOrder(amount: Double, orderId: String) {
//        val request = userId?.let { WalletActionRequest(user_id = it, amount = amount, order_id = orderId) }
//        if (request != null) {
//            api.payOrder(request).enqueue(object : Callback<WalletActionResponse> {
//                override fun onResponse(
//                    call: Call<WalletActionResponse>,
//                    response: Response<WalletActionResponse>
//                ) {
//                    if (response.isSuccessful) {
//                        val newBalance = response.body()?.balance ?: 0.0
//                        tvBalance.text = "Wallet Balance: ₹$newBalance"
//                        fetchTransactions()
//                        Toast.makeText(this@WalletActivity, "Payment successful", Toast.LENGTH_SHORT).show()
//                    } else {
//                        Toast.makeText(this@WalletActivity, "Payment failed", Toast.LENGTH_SHORT).show()
//                    }
//                }
//
//                override fun onFailure(call: Call<WalletActionResponse>, t: Throwable) {
//                    t.printStackTrace()
//                    Toast.makeText(this@WalletActivity, "Error processing payment", Toast.LENGTH_SHORT).show()
//                }
//            })
//        }
//    }
//
//    fun refundOrder(amount: Double, orderId: String) {
//        val request = userId?.let { WalletActionRequest(user_id = it, amount = amount, order_id = orderId) }
//        if (request != null) {
//            api.refundOrder(request).enqueue(object : Callback<WalletActionResponse> {
//                override fun onResponse(
//                    call: Call<WalletActionResponse>,
//                    response: Response<WalletActionResponse>
//                ) {
//                    if (response.isSuccessful) {
//                        val newBalance = response.body()?.balance ?: 0.0
//                        tvBalance.text = "Wallet Balance: ₹$newBalance"
//                        fetchTransactions()
//                        Toast.makeText(this@WalletActivity, "Refund successful", Toast.LENGTH_SHORT).show()
//                    } else {
//                        Toast.makeText(this@WalletActivity, "Refund failed", Toast.LENGTH_SHORT).show()
//                    }
//                }
//
//                override fun onFailure(call: Call<WalletActionResponse>, t: Throwable) {
//                    t.printStackTrace()
//                    Toast.makeText(this@WalletActivity, "Error processing refund", Toast.LENGTH_SHORT).show()
//                }
//            })
//        }
//    }
//}


//package com.example.groceryshoppingapp
//
//import android.app.AlertDialog
//import android.os.Bundle
//import android.widget.Button
//import android.widget.EditText
//import android.widget.TextView
//import android.widget.Toast
//import androidx.appcompat.app.AppCompatActivity
//import androidx.recyclerview.widget.LinearLayoutManager
//import androidx.recyclerview.widget.RecyclerView
//import com.example.groceryshoppingapp.adapters.WalletTransactionAdapter
//import com.example.groceryshoppingapp.models.WalletActionRequest
//import com.example.groceryshoppingapp.models.WalletActionResponse
//import com.example.groceryshoppingapp.models.WalletBalanceResponse
//import com.example.groceryshoppingapp.models.WalletTransaction
//import com.example.groceryshoppingapp.network.ApiService
//import com.example.groceryshoppingapp.network.RetrofitClient
//import com.example.groceryshoppingapp.utils.SessionManager
//import com.razorpay.Checkout
//import com.razorpay.PaymentResultListener
//import org.json.JSONObject
//import retrofit2.Call
//import retrofit2.Callback
//import retrofit2.Response

//class WalletActivity : AppCompatActivity(), PaymentResultListener {
//
//    private lateinit var tvBalance: TextView
//    private lateinit var rvTransactions: RecyclerView
//    private lateinit var btnAddMoney: Button
//    private val transactions = mutableListOf<WalletTransaction>()
//    private lateinit var adapter: WalletTransactionAdapter
//
//    private lateinit var api: ApiService
//    private var userId: String? = null
//
//    private var amountToAdd = 0.0  // ← Store entered amount
//
//    override fun onCreate(savedInstanceState: Bundle?) {
//        super.onCreate(savedInstanceState)
//        setContentView(R.layout.activity_wallet)
//
//        Checkout.preload(applicationContext)
//
//        userId = SessionManager.getFirebaseId(this)
//
//        tvBalance = findViewById(R.id.tvBalance)
//        rvTransactions = findViewById(R.id.rvTransactions)
//        btnAddMoney = findViewById(R.id.btnAddMoney)
//
//        adapter = WalletTransactionAdapter(transactions)
//        rvTransactions.layoutManager = LinearLayoutManager(this)
//        rvTransactions.adapter = adapter
//
//        api = RetrofitClient.getInstance(this).create(ApiService::class.java)
//
//        fetchWalletBalance()
//        fetchTransactions()
//
//        btnAddMoney.setOnClickListener {
//            openAddMoneyDialog()
//        }
//    }
//
//    private fun openAddMoneyDialog() {
//        val dialogView = layoutInflater.inflate(R.layout.dialog_add_money, null)
//        val etAmount = dialogView.findViewById<EditText>(R.id.etAddAmount)
//
//        AlertDialog.Builder(this)
//            .setTitle("Add Money")
//            .setView(dialogView)
//            .setPositiveButton("Add") { _, _ ->
//                val input = etAmount.text.toString()
//
//                if (input.isEmpty()) {
//                    Toast.makeText(this, "Enter valid amount", Toast.LENGTH_SHORT).show()
//                    return@setPositiveButton
//                }
//
//                amountToAdd = input.toDouble()
//
//                startRazorpayPayment(amountToAdd)
//            }
//            .setNegativeButton("Cancel", null)
//            .show()
//    }
//
//    private fun startRazorpayPayment(amount: Double) {
//        val checkout = Checkout()
//        checkout.setKeyID("rzp_test_123456789")   // replace with your Razorpay Key
//
//        try {
//            val options = JSONObject()
//            options.put("name", "Grocery App")
//            options.put("description", "Wallet Top-up")
//
//            val finalAmount = (amount * 100).toInt()
//            options.put("amount", finalAmount)
//
//            val prefill = JSONObject()
//            prefill.put("email", "test@test.com")
//            prefill.put("contact", "9999999999")
//
//            options.put("prefill", prefill)
//
//            checkout.open(this, options)
//
//        } catch (e: Exception) {
//            e.printStackTrace()
//        }
//    }
//
//    // Razorpay Success
//    override fun onPaymentSuccess(razorpayPaymentId: String?) {
//        Toast.makeText(this, "Payment Successful!", Toast.LENGTH_SHORT).show()
//        addMoney(amountToAdd)  // wallet update
//    }
//
//    // Razorpay Error
//    override fun onPaymentError(code: Int, msg: String?) {
//        Toast.makeText(this, "Payment Failed!", Toast.LENGTH_SHORT).show()
//    }
//
//    // ---------- Existing Code (No changes below here) ----------
//
//    private fun fetchWalletBalance() {
//        if (userId != null) {
//            api.getWalletBalance(userId!!).enqueue(object : Callback<WalletBalanceResponse> {
//                override fun onResponse(
//                    call: Call<WalletBalanceResponse>,
//                    response: Response<WalletBalanceResponse>
//                ) {
//                    if (response.isSuccessful) {
//                        val balance = response.body()?.balance ?: 0.0
//                        tvBalance.text = "Wallet Balance: ₹$balance"
//                    }
//                }
//
//                override fun onFailure(call: Call<WalletBalanceResponse>, t: Throwable) {
//                    Toast.makeText(this@WalletActivity, "Error fetching balance", Toast.LENGTH_SHORT).show()
//                }
//            })
//        }
//    }
//
//    private fun fetchTransactions() {
//        if (userId != null) {
//            api.getWalletTransactions(userId!!).enqueue(object :
//                Callback<List<WalletTransaction>> {
//                override fun onResponse(call: Call<List<WalletTransaction>>, response: Response<List<WalletTransaction>>) {
//                    if (response.isSuccessful) {
//                        transactions.clear()
//                        response.body()?.let { transactions.addAll(it) }
//                        adapter.notifyDataSetChanged()
//                    }
//                }
//
//                override fun onFailure(call: Call<List<WalletTransaction>>, t: Throwable) {
//                    Toast.makeText(this@WalletActivity, "Error fetching transactions", Toast.LENGTH_SHORT).show()
//                }
//            })
//        }
//    }
//
//    private fun addMoney(amount: Double) {
//        val request = userId?.let { WalletActionRequest(it, amount) }
//
//        if (request != null) {
//            api.addMoney(request).enqueue(object : Callback<WalletActionResponse> {
//                override fun onResponse(call: Call<WalletActionResponse>, response: Response<WalletActionResponse>) {
//                    if (response.isSuccessful) {
//                        val newBalance = response.body()?.balance ?: 0.0
//                        tvBalance.text = "Wallet Balance: ₹$newBalance"
//                        fetchTransactions()
//                        Toast.makeText(this@WalletActivity, "Money added", Toast.LENGTH_SHORT).show()
//                    }
//                }
//
//                override fun onFailure(call: Call<WalletActionResponse>, t: Throwable) {
//                    Toast.makeText(this@WalletActivity, "Error adding money", Toast.LENGTH_SHORT).show()
//                }
//            })
//        }
//    }
//}


package com.example.groceryshoppingapp

import android.app.AlertDialog
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.WalletTransactionAdapter
import com.example.groceryshoppingapp.models.WalletActionRequest
import com.example.groceryshoppingapp.models.WalletActionResponse
import com.example.groceryshoppingapp.models.WalletBalanceResponse
import com.example.groceryshoppingapp.models.WalletTransaction
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.network.WalletOrderRequest
import com.example.groceryshoppingapp.network.WalletOrderResponse
import com.example.groceryshoppingapp.utils.SessionManager
import com.razorpay.Checkout
import com.razorpay.PaymentResultListener
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class WalletActivity : AppCompatActivity(), PaymentResultListener {

    private lateinit var tvBalance: TextView
    private lateinit var rvTransactions: RecyclerView
    private lateinit var btnAddMoney: Button
    private val transactions = mutableListOf<WalletTransaction>()
    private lateinit var adapter: WalletTransactionAdapter

    private lateinit var api: ApiService
    private lateinit var paymentManager: PaymentManager

    private var userId: String? = null
    private var backendOrderId: String? = null
    private var amountToAdd = 0.0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_wallet)

        Checkout.preload(applicationContext)

        api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        paymentManager = PaymentManager(this)

        userId = SessionManager.getCustomerId(this)

        tvBalance = findViewById(R.id.tvBalance)
        rvTransactions = findViewById(R.id.rvTransactions)
        btnAddMoney = findViewById(R.id.btnAddMoney)

        adapter = WalletTransactionAdapter(transactions)
        rvTransactions.layoutManager = LinearLayoutManager(this)
        rvTransactions.adapter = adapter

        fetchWalletBalance()
        fetchTransactions()

        btnAddMoney.setOnClickListener {
            openAddMoneyDialog()
        }
    }

    private fun openAddMoneyDialog() {
        val dialogView = layoutInflater.inflate(R.layout.dialog_add_money, null)
        val etAmount = dialogView.findViewById<EditText>(R.id.etAddAmount)

        AlertDialog.Builder(this)
            .setTitle("Add Money")
            .setView(dialogView)
            .setPositiveButton("Add") { _, _ ->
                val input = etAmount.text.toString()
                if (input.isEmpty()) {
                    Toast.makeText(this, "Enter valid amount", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                amountToAdd = try {
                    input.toDouble()
                } catch (e: Exception) {
                    Toast.makeText(this, "Invalid amount", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                createBackendOrder(amountToAdd)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun createBackendOrder(amount: Double) {
        val uid = userId ?: run {
            Toast.makeText(this, "User not logged in", Toast.LENGTH_SHORT).show()
            return
        }

        val request = WalletOrderRequest(
            user_id = uid,
            amount = amount
        )

        api.createWalletOrder(request).enqueue(object : Callback<WalletOrderResponse> {
            override fun onResponse(
                call: Call<WalletOrderResponse>,
                resp: Response<WalletOrderResponse>
            ) {
                if (resp.isSuccessful) {
                    val body = resp.body()
                    if (body == null) {
                        Toast.makeText(this@WalletActivity, "Invalid response", Toast.LENGTH_SHORT).show()
                        return
                    }

                    backendOrderId = body.backend_order_id
                    val razorpayOrderId = body.razorpay_order_id

                    paymentManager.startRazorpayCheckout(
                        "Wallet Recharge",
                        amountToAdd,
                        razorpayOrderId
                    )

                } else {
                    Toast.makeText(this@WalletActivity, "Order creation failed", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<WalletOrderResponse>, t: Throwable) {
                Toast.makeText(this@WalletActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    override fun onPaymentSuccess(paymentId: String?) {
        paymentManager.verifyPayment(
            backendOrderId,
            paymentId,
            PaymentManager.lastRazorpayOrderId,
            PaymentManager.lastSignature
        )
    }

    override fun onPaymentError(code: Int, msg: String?) {
        Toast.makeText(this, "Payment Failed: $msg", Toast.LENGTH_SHORT).show()
    }

    fun onPaymentVerified() {
        val uid = userId ?: return
        val request = WalletActionRequest(user_id = uid, amount = amountToAdd)

        api.addMoney(request).enqueue(object : Callback<WalletActionResponse> {
            override fun onResponse(
                call: Call<WalletActionResponse>,
                response: Response<WalletActionResponse>
            ) {
                if (response.isSuccessful) {
                    val newBalance = response.body()?.balance ?: 0.0
                    tvBalance.text = "Wallet Balance: ₹$newBalance"
                    fetchTransactions()
                    Toast.makeText(
                        this@WalletActivity,
                        "Wallet topped up ₹$amountToAdd",
                        Toast.LENGTH_SHORT
                    ).show()
                } else {
                    Toast.makeText(this@WalletActivity, "Failed to update wallet", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<WalletActionResponse>, t: Throwable) {
                Toast.makeText(this@WalletActivity, "Error updating wallet: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun fetchWalletBalance() {
        val uid = userId ?: return
        api.getWalletBalance(uid).enqueue(object : Callback<WalletBalanceResponse> {
            override fun onResponse(
                call: Call<WalletBalanceResponse>,
                response: Response<WalletBalanceResponse>
            ) {
                if (response.isSuccessful) {
                    val balance = response.body()?.balance ?: 0.0
                    tvBalance.text = "Wallet Balance: ₹$balance"
                }
            }

            override fun onFailure(call: Call<WalletBalanceResponse>, t: Throwable) {
                Toast.makeText(this@WalletActivity, "Error fetching balance", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun fetchTransactions() {
        val uid = userId ?: return
        api.getWalletTransactions(uid).enqueue(object : Callback<List<WalletTransaction>> {
            override fun onResponse(
                call: Call<List<WalletTransaction>>,
                response: Response<List<WalletTransaction>>
            ) {
                if (response.isSuccessful) {
                    transactions.clear()
                    response.body()?.let { transactions.addAll(it) }
                    adapter.notifyDataSetChanged()
                }
            }

            override fun onFailure(call: Call<List<WalletTransaction>>, t: Throwable) {
                Toast.makeText(this@WalletActivity, "Error fetching transactions", Toast.LENGTH_SHORT).show()
            }
        })
    }
}
