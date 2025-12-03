package com.example.groceryshoppingapp

import android.app.AlertDialog
import android.os.Bundle
import android.os.Handler
import android.view.View
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.adapters.KhataTransactionAdapter
import com.example.groceryshoppingapp.databinding.ActivityKhataCustomerDetailBinding
import com.example.groceryshoppingapp.models.KhataAccount
import com.example.groceryshoppingapp.models.KhataLedgerResponse
import com.example.groceryshoppingapp.models.KhataTransaction
import com.example.groceryshoppingapp.models.KhataTransactionRequest
import com.example.groceryshoppingapp.network.ApiResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.*
import kotlin.math.abs

class KhataCustomerDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityKhataCustomerDetailBinding
    private lateinit var api: ApiService
    private lateinit var account: KhataAccount

    private lateinit var adapter: KhataTransactionAdapter
    private val transactions = mutableListOf<KhataTransaction>()

    private var isReadOnly = true
    private val handler = Handler()

    // Auto refresh for customer
    private val customerAutoRefreshRunnable = object : Runnable {
        override fun run() {
            if (isReadOnly) {
                loadLedger(false)
                handler.postDelayed(this, 4000)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityKhataCustomerDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)

        api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        account = intent.getParcelableExtra("account")
            ?: run {
                Toast.makeText(this, "Missing account", Toast.LENGTH_SHORT).show()
                finish()
                return
            }

        isReadOnly = intent.getBooleanExtra("isReadOnly", true)

        when (SessionManager.getRole(this)) {
            "shopowner" -> isReadOnly = false
            "customer" -> isReadOnly = true
        }

        setupRecycler()
        setupButtons()
        setupPullToRefresh()
        bindHeader()

        loadLedger(true)

        if (isReadOnly) {
            handler.post(customerAutoRefreshRunnable)
        }
    }

    private fun setupRecycler() {
        adapter = KhataTransactionAdapter(transactions)
        binding.rvTransactions.layoutManager = LinearLayoutManager(this)
        binding.rvTransactions.adapter = adapter
    }

    private fun setupPullToRefresh() {
        binding.swipeRefresh.setOnRefreshListener {
            loadLedger(true)
        }
    }

    private fun setupButtons() {
        binding.btnBack.setOnClickListener { finish() }

        if (isReadOnly) {
            binding.layoutActions.visibility = View.GONE
        } else {
            binding.layoutActions.visibility = View.VISIBLE
            binding.btnAddDebit.setOnClickListener { openAddDialog("debit") }
            binding.btnAddCredit.setOnClickListener { openAddDialog("credit") }
        }
    }

    private fun bindHeader() {
        binding.tvCustomerName.text = account.customerName ?: "Customer"
        binding.tvCustomerPhone.text = account.phone ?: "-"
        updateBalanceUI(account.balance ?: 0.0)
        updateLastUpdated()
    }

    private fun updateBalanceUI(balance: Double) {
        val absVal = abs(balance)
        binding.tvBalance.text = "₹${String.format("%.2f", absVal)}"

        binding.tvBalanceLabel.text = when {
            balance > 0 -> if (isReadOnly) "You owe shop" else "Customer owes you"
            balance < 0 -> if (isReadOnly) "Shop owes you" else "You owe customer"
            else -> "All Clear"
        }
    }

    private fun updateLastUpdated() {
        val sdf = SimpleDateFormat("hh:mm a", Locale.getDefault())
        binding.tvLastUpdated.text = "Last updated: ${sdf.format(Date())}"
    }

    private fun loadLedger(showLoader: Boolean) {
        if (showLoader) binding.swipeRefresh.isRefreshing = true

        val shopId = account.shopId ?: return
        val customerId = account.customerId ?: return

        api.getKhataLedger(shopId, customerId)
            .enqueue(object : Callback<KhataLedgerResponse> {
                override fun onResponse(
                    call: Call<KhataLedgerResponse>,
                    response: Response<KhataLedgerResponse>
                ) {
                    binding.swipeRefresh.isRefreshing = false
                    if (!response.isSuccessful) return

                    val body = response.body() ?: return

                    // Keep account fresh
                    account.balance = body.account?.balance
                    account.customerName = body.account?.customerName
                    account.phone = body.account?.phone
                    account.shopName = body.account?.shopName

                    transactions.clear()
                    body.transactions?.let { transactions.addAll(it) }
                    adapter.notifyDataSetChanged()

                    updateBalanceUI(account.balance ?: 0.0)
                    updateLastUpdated()
                }

                override fun onFailure(call: Call<KhataLedgerResponse>, t: Throwable) {
                    binding.swipeRefresh.isRefreshing = false
                    Toast.makeText(
                        this@KhataCustomerDetailActivity,
                        "Error: ${t.message}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            })
    }

    private fun openAddDialog(type: String) {
        val view = layoutInflater.inflate(R.layout.dialog_add_khata_transaction, null)
        val etAmount = view.findViewById<EditText>(R.id.etAmount)
        val etNote = view.findViewById<EditText>(R.id.etNote)

        val title = if (type == "debit") "Add Debit" else "Add Credit"

        AlertDialog.Builder(this)
            .setTitle(title)
            .setView(view)
            .setPositiveButton("Save") { _, _ ->
                val amount = etAmount.text.toString().toDoubleOrNull()
                if (amount == null || amount <= 0) {
                    Toast.makeText(this, "Enter valid amount", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                addTransaction(type, amount, etNote.text.toString())
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun addTransaction(type: String, amount: Double, note: String) {
        val shopId = account.shopId ?: return
        val customerId = account.customerId ?: return

        val request = KhataTransactionRequest(
            shop_id = shopId,
            customer_id = customerId,
            type = type,
            amount = amount,
            note = note
        )

        api.addKhataTransaction(request)
            .enqueue(object : Callback<ApiResponse> {
                override fun onResponse(
                    call: Call<ApiResponse>,
                    response: Response<ApiResponse>
                ) {
                    if (!response.isSuccessful) {
                        Toast.makeText(
                            this@KhataCustomerDetailActivity,
                            "Failed to save",
                            Toast.LENGTH_SHORT
                        ).show()
                        return
                    }

                    Toast.makeText(
                        this@KhataCustomerDetailActivity,
                        "Saved",
                        Toast.LENGTH_SHORT
                    ).show()

                    loadLedger(true)
                }

                override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
                    Toast.makeText(
                        this@KhataCustomerDetailActivity,
                        "Error: ${t.message}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            })
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacks(customerAutoRefreshRunnable)
    }
}
