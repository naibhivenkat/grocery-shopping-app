package com.example.groceryshoppingapp

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.os.Bundle
import android.view.animation.AnimationUtils
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.adapters.WalletTransactionAdapter
import com.example.groceryshoppingapp.models.WalletBalanceResponse
import com.example.groceryshoppingapp.models.WalletTransaction
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.network.WalletOrderRequest
import com.example.groceryshoppingapp.network.WalletOrderResponse
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.android.material.bottomsheet.BottomSheetDialog
import com.google.android.material.card.MaterialCardView
import com.google.android.material.chip.ChipGroup
import com.razorpay.Checkout
import com.razorpay.PaymentData
import com.razorpay.PaymentResultWithDataListener
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import android.graphics.Color

class WalletActivity : AppCompatActivity(), PaymentResultWithDataListener {

    private lateinit var tvBalance: TextView
    private lateinit var rvTransactions: androidx.recyclerview.widget.RecyclerView
    private lateinit var btnAddMoney: Button
    private lateinit var chipGroup: ChipGroup

    private val transactions = mutableListOf<WalletTransaction>()
    private val filteredList = mutableListOf<WalletTransaction>()

    private lateinit var adapter: WalletTransactionAdapter
    private lateinit var api: ApiService
    private lateinit var paymentManager: PaymentManager

    private var userId: String? = null
    private var backendOrderId: String? = null
    private var amountToAdd = 0.0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_wallet)

        // Razorpay preload
        Checkout.preload(applicationContext)

        // Init API + Payment + Session
        api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        paymentManager = PaymentManager(this)
        userId = SessionManager.getCustomerId(this)

        // Bind UI

        val walletBg = findViewById<LinearLayout>(R.id.walletCardBg)
        val anim = AnimationUtils.loadAnimation(this, R.anim.wallet_glow)
        walletBg.startAnimation(anim)

        tvBalance = findViewById(R.id.tvBalance)
        rvTransactions = findViewById(R.id.rvTransactions)
        btnAddMoney = findViewById(R.id.btnAddMoney)
        chipGroup = findViewById(R.id.chipFilterGroup)


        // RecyclerView
        adapter = WalletTransactionAdapter(filteredList) { tx ->
            showTransactionDetails(tx)
        }

        rvTransactions.layoutManager = LinearLayoutManager(this)
        rvTransactions.adapter = adapter

        // Filters
        setupFilterListeners()

        // Load data
        fetchWalletBalance()
        fetchTransactions()

        // Add Money
        btnAddMoney.setOnClickListener { openAddMoneyDialog() }
    }

    // ------------------ FILTERS ------------------

    private fun setupFilterListeners() {
        chipGroup.setOnCheckedStateChangeListener { _, _ -> applyFilter() }
    }

    private fun applyFilter() {
        val selectedId = chipGroup.checkedChipId
        filteredList.clear()

        when (selectedId) {
            R.id.chipCredit ->
                filteredList.addAll(transactions.filter { it.type.equals("Deposit", true) })

            R.id.chipDebit ->
                filteredList.addAll(transactions.filter { it.type.equals("Payment", true) })

            R.id.chipRefund ->
                filteredList.addAll(
                    transactions.filter {
                        it.type.equals("Refund", true) ||
                                it.type.equals("Partial Refund", true)
                    }
                )


            else -> filteredList.addAll(transactions)
        }

        adapter.notifyDataSetChanged()
    }

    @SuppressLint("SetTextI18n")
    private fun showTransactionDetails(tx: WalletTransaction) {
        val view = layoutInflater.inflate(R.layout.bottomsheet_transaction_details, null)
        val dialog = BottomSheetDialog(this)
        dialog.setContentView(view)

        val tvType = view.findViewById<TextView>(R.id.tvType)
        val tvAmount = view.findViewById<TextView>(R.id.tvAmount)
        val tvDate = view.findViewById<TextView>(R.id.tvDate)
        val tvOrderId = view.findViewById<TextView>(R.id.tvOrderId)

        // Set common fields
        tvType.text = tx.type
        tvAmount.text = "₹${tx.amount}"
        tvDate.text = tx.dateTime
        tvOrderId.text = tx.orderId ?: "No Order Linked"

        // --------------------------------------------
        // 🔥 Highlight Partial Refund in ORANGE
        // --------------------------------------------
        if (tx.type.equals("Partial Refund", true)) {
            val orange = Color.parseColor("#FF9800")

            tvType.setTextColor(orange)
            tvAmount.setTextColor(orange)

            // Format text nicely
            tvType.text = "Partial Refund"
        }

        // (Normal refund shows purple in the list, but here it stays default)
        // --------------------------------------------

        dialog.show()
    }


    // ------------------ ADD MONEY ------------------

    private fun openAddMoneyDialog() {
        val dialogView = layoutInflater.inflate(R.layout.dialog_add_money, null)
        val input = dialogView.findViewById<EditText>(R.id.etAddAmount)

        AlertDialog.Builder(this)
            .setTitle("Add Money")
            .setView(dialogView)
            .setPositiveButton("Add") { _, _ ->
                val value = input.text.toString()

                if (value.isEmpty()) {
                    Toast.makeText(this, "Enter amount", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                amountToAdd = value.toDoubleOrNull() ?: 0.0
                if (amountToAdd <= 0) {
                    Toast.makeText(this, "Invalid amount", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                createBackendOrder(amountToAdd)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ------------------ CREATE ORDER ------------------

    private fun createBackendOrder(amount: Double) {
        api.createWalletOrder(WalletOrderRequest(userId!!, amount))
            .enqueue(object : Callback<WalletOrderResponse> {

                override fun onResponse(call: Call<WalletOrderResponse>, resp: Response<WalletOrderResponse>) {
                    if (!resp.isSuccessful) {
                        Toast.makeText(this@WalletActivity, "Error creating order", Toast.LENGTH_SHORT).show()
                        return
                    }

                    val body = resp.body() ?: return
                    backendOrderId = body.backend_order_id

                    paymentManager.startWalletTopUp(amount, body.razorpay_order_id)
                }

                override fun onFailure(call: Call<WalletOrderResponse>, t: Throwable) {
                    Toast.makeText(this@WalletActivity, "Network error", Toast.LENGTH_SHORT).show()
                }
            })
    }

    // ------------------ RAZORPAY CALLBACKS ------------------

    override fun onPaymentSuccess(paymentId: String?, data: PaymentData?) {
        paymentManager.verifyPayment(
            backendOrderId,
            paymentId,
            data?.orderId,
            data?.signature
        )
    }

    override fun onPaymentError(code: Int, msg: String?, data: PaymentData?) {
        Toast.makeText(this, "Payment Failed", Toast.LENGTH_SHORT).show()
    }

    fun onPaymentVerified() {
        fetchWalletBalance()
        fetchTransactions()
        Toast.makeText(this, "Wallet updated successfully", Toast.LENGTH_SHORT).show()
    }

    // ------------------ FETCH BALANCE ------------------

    private fun fetchWalletBalance() {
        api.getWalletBalance(userId!!).enqueue(object : Callback<WalletBalanceResponse> {

            override fun onResponse(call: Call<WalletBalanceResponse>, resp: Response<WalletBalanceResponse>) {
                tvBalance.text = "₹${resp.body()?.balance ?: 0.0}"
            }

            override fun onFailure(call: Call<WalletBalanceResponse>, t: Throwable) {}
        })
    }

    // ------------------ FETCH TRANSACTIONS ------------------

    private fun fetchTransactions() {
        api.getWalletTransactions(userId!!).enqueue(object : Callback<List<WalletTransaction>> {

            override fun onResponse(call: Call<List<WalletTransaction>>, resp: Response<List<WalletTransaction>>) {
                transactions.clear()
                resp.body()?.let { transactions.addAll(it) }
                applyFilter()
            }

            override fun onFailure(call: Call<List<WalletTransaction>>, t: Throwable) {}
        })
    }
}
