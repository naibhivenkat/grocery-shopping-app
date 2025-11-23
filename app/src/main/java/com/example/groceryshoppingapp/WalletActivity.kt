package com.example.groceryshoppingapp

import android.os.Bundle
import android.widget.Button
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
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class WalletActivity : AppCompatActivity() {

    private lateinit var tvBalance: TextView
    private lateinit var rvTransactions: RecyclerView
    private lateinit var btnAddMoney: Button
    private val transactions = mutableListOf<WalletTransaction>()
    private lateinit var adapter: WalletTransactionAdapter

    private lateinit var api: ApiService
    private var userId: String? = null // ⚠ move initialization to onCreate

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_wallet)

        // ⚡ Initialize userId here
        userId = SessionManager.getCustomerId(this)

        tvBalance = findViewById(R.id.tvBalance)
        rvTransactions = findViewById(R.id.rvTransactions)
        btnAddMoney = findViewById(R.id.btnAddMoney)

        adapter = WalletTransactionAdapter(transactions)
        rvTransactions.layoutManager = LinearLayoutManager(this)
        rvTransactions.adapter = adapter

        api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        fetchWalletBalance()
        fetchTransactions()

        btnAddMoney.setOnClickListener {
            // Replace 100.0 with user input amount
            addMoney(100.0)
        }
    }

    private fun fetchWalletBalance() {
        if (userId != null) {
            api.getWalletBalance(userId!!).enqueue(object : Callback<WalletBalanceResponse> {
                override fun onResponse(
                    call: Call<WalletBalanceResponse>,
                    response: Response<WalletBalanceResponse>
                ) {
                    if (response.isSuccessful) {
                        val balance = response.body()?.balance ?: 0.0
                        tvBalance.text = "Wallet Balance: ₹$balance"
                    } else {
                        Toast.makeText(this@WalletActivity, "Failed to fetch balance", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<WalletBalanceResponse>, t: Throwable) {
                    t.printStackTrace()
                    Toast.makeText(this@WalletActivity, "Error fetching balance", Toast.LENGTH_SHORT).show()
                }
            })
        }
    }

    private fun fetchTransactions() {
        if (userId != null) {
            api.getWalletTransactions(userId!!).enqueue(object : Callback<List<WalletTransaction>> {
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
                    t.printStackTrace()
                    Toast.makeText(this@WalletActivity, "Error fetching transactions", Toast.LENGTH_SHORT).show()
                }
            })
        }
    }

    private fun addMoney(amount: Double) {
        val request = userId?.let { WalletActionRequest(user_id = it, amount = amount) }
        if (request != null) {
            api.addMoney(request).enqueue(object : Callback<WalletActionResponse> {
                override fun onResponse(
                    call: Call<WalletActionResponse>,
                    response: Response<WalletActionResponse>
                ) {
                    if (response.isSuccessful) {
                        val newBalance = response.body()?.balance ?: 0.0
                        tvBalance.text = "Wallet Balance: ₹$newBalance"
                        fetchTransactions()
                        Toast.makeText(this@WalletActivity, "Money added successfully", Toast.LENGTH_SHORT).show()
                    } else {
                        Toast.makeText(this@WalletActivity, "Failed to add money", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<WalletActionResponse>, t: Throwable) {
                    t.printStackTrace()
                    Toast.makeText(this@WalletActivity, "Error adding money", Toast.LENGTH_SHORT).show()
                }
            })
        }
    }

    fun payOrder(amount: Double, orderId: String) {
        val request = userId?.let { WalletActionRequest(user_id = it, amount = amount, order_id = orderId) }
        if (request != null) {
            api.payOrder(request).enqueue(object : Callback<WalletActionResponse> {
                override fun onResponse(
                    call: Call<WalletActionResponse>,
                    response: Response<WalletActionResponse>
                ) {
                    if (response.isSuccessful) {
                        val newBalance = response.body()?.balance ?: 0.0
                        tvBalance.text = "Wallet Balance: ₹$newBalance"
                        fetchTransactions()
                        Toast.makeText(this@WalletActivity, "Payment successful", Toast.LENGTH_SHORT).show()
                    } else {
                        Toast.makeText(this@WalletActivity, "Payment failed", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<WalletActionResponse>, t: Throwable) {
                    t.printStackTrace()
                    Toast.makeText(this@WalletActivity, "Error processing payment", Toast.LENGTH_SHORT).show()
                }
            })
        }
    }

    fun refundOrder(amount: Double, orderId: String) {
        val request = userId?.let { WalletActionRequest(user_id = it, amount = amount, order_id = orderId) }
        if (request != null) {
            api.refundOrder(request).enqueue(object : Callback<WalletActionResponse> {
                override fun onResponse(
                    call: Call<WalletActionResponse>,
                    response: Response<WalletActionResponse>
                ) {
                    if (response.isSuccessful) {
                        val newBalance = response.body()?.balance ?: 0.0
                        tvBalance.text = "Wallet Balance: ₹$newBalance"
                        fetchTransactions()
                        Toast.makeText(this@WalletActivity, "Refund successful", Toast.LENGTH_SHORT).show()
                    } else {
                        Toast.makeText(this@WalletActivity, "Refund failed", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<WalletActionResponse>, t: Throwable) {
                    t.printStackTrace()
                    Toast.makeText(this@WalletActivity, "Error processing refund", Toast.LENGTH_SHORT).show()
                }
            })
        }
    }
}
