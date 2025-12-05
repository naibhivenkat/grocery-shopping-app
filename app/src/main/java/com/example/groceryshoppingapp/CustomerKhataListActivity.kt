package com.example.groceryshoppingapp
import android.graphics.Color
import android.content.Intent
import android.os.Bundle
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
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.CashPaymentRequest
import com.example.groceryshoppingapp.network.PayKhataRequest
import com.example.groceryshoppingapp.network.PayKhataResponse
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.firebase.firestore.ktx.firestore
import com.google.firebase.ktx.Firebase
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.*
import com.example.groceryshoppingapp.network.ApiResponse


class CustomerKhataListActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCustomerKhataListBinding
    private lateinit var api: ApiService
    private val accounts = mutableListOf<KhataAccount>()
    private lateinit var adapter: KhataAccountAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityCustomerKhataListBinding.inflate(layoutInflater)
        setContentView(binding.root)

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

    private fun loadAccounts() {
        val customerId = SessionManager.getCustomerId(this) ?: return
        binding.swipeRefresh.isRefreshing = true

        api.getMyKhataAccounts(customerId)
            .enqueue(object : Callback<KhataAccountsResponse> {
                override fun onResponse(call: Call<KhataAccountsResponse>, response: Response<KhataAccountsResponse>) {
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
                    Toast.makeText(this@CustomerKhataListActivity, t.message, Toast.LENGTH_SHORT).show()
                }
            })
    }

    private fun updateLastUpdated() {
        val sdf = SimpleDateFormat("hh:mm a", Locale.getDefault())
        binding.tvLastUpdated.text = "Updated: ${sdf.format(Date())}"
    }

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

                    // ⭐ NEW — get pending fields
                    acc.pendingCash = doc.getDouble("pending_cash")
                    acc.pendingStatus = doc.getString("pending_status")
                    acc.pendingRequestId = doc.getString("pending_request_id")

                    accounts.add(acc)
                }

                adapter.notifyDataSetChanged()
                updateLastUpdated()
            }
    }

    // ⭐ NEW — fetch wallet balance
    private fun fetchWalletBalance(callback: (Double) -> Unit) {
        val userId = SessionManager.getCustomerId(this) ?: return

        api.getWalletBalance(userId)
            .enqueue(object : Callback<WalletBalanceResponse> {
                override fun onResponse(call: Call<WalletBalanceResponse>, response: Response<WalletBalanceResponse>) {
                    val balance = response.body()?.balance ?: 0.0
                    SessionManager.saveWalletBalance(this@CustomerKhataListActivity, balance)
                    callback(balance)
                }

                override fun onFailure(call: Call<WalletBalanceResponse>, t: Throwable) {
                    callback(0.0)
                }
            })
    }

    // ⭐ NEW — Payment Method dialog
    private fun showPaymentMethodDialog(acc: KhataAccount) {

        // If cash pending -> block payment
        if (acc.pendingStatus == "pending") {
            Toast.makeText(this, "Cash payment request pending approval", Toast.LENGTH_LONG).show()
            return
        }

        val options = arrayOf("Wallet", "Cash Payment")

        AlertDialog.Builder(this)
            .setTitle("Choose Payment Method")
            .setItems(options) { _, which ->
                when (which) {
                    0 -> fetchWalletBalance { balance ->
                        showWalletConfirmation(acc, balance)
                    }

                    1 -> showCashAmountDialog(acc) // ⭐ NEW
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ⭐ NEW — Cash input
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

    // ⭐ NEW — Send cash payment request to backend
    private fun sendCashPaymentRequest(acc: KhataAccount, amount: Double) {

        val request = CashPaymentRequest(
            customer_id = SessionManager.getCustomerId(this) ?: "",
            shop_id = acc.shopId ?: "",
            amount = amount
        )

        api.createCashPaymentRequest(request).enqueue(object : Callback<ApiResponse> {
            override fun onResponse(call: Call<ApiResponse>, response: Response<ApiResponse>) {
                if (response.isSuccessful && response.body()?.success == true) {
                    Toast.makeText(this@CustomerKhataListActivity,
                        "Cash payment request sent to shop owner",
                        Toast.LENGTH_LONG).show()
                } else {
                    Toast.makeText(this@CustomerKhataListActivity,
                        response.body()?.message ?: "Failed",
                        Toast.LENGTH_LONG).show()
                }
            }

            override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
                Toast.makeText(this@CustomerKhataListActivity, t.message, Toast.LENGTH_LONG).show()
            }
        })
    }



    private fun showWalletConfirmation(acc: KhataAccount, walletBalance: Double) {

        val amountDue = acc.balance ?: 0.0

        val message = if (walletBalance < amountDue) {
            "Wallet Balance: ₹$walletBalance\n" +
                    "Amount to Pay: ₹$amountDue\n\n" +
                    "⚠️ Insufficient Wallet Balance\nYou can still enter a partial amount."
        } else {
            "Wallet Balance: ₹$walletBalance\n" +
                    "Amount to Pay: ₹$amountDue\n\n" +
                    "Do you want to continue?"
        }

        val dialog = AlertDialog.Builder(this)
            .setTitle("Confirm Wallet Payment")
            .setMessage(message)
            .setPositiveButton("Yes", null)
            .setNegativeButton("No", null)
            .create()

        dialog.setOnShowListener {
            val btnYes = dialog.getButton(AlertDialog.BUTTON_POSITIVE)

            // ALWAYS allow continuing to amount entry
            btnYes.setOnClickListener {
                dialog.dismiss()
                showAmountInputDialog(acc)
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

        // 🔥 Red warning text
        val warning = TextView(this)
        warning.setTextColor(Color.RED)
        warning.textSize = 13f
        warning.text = ""

        // Layout to place input + warning
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

            // Disable initially
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

            // Live Validation
            input.addTextChangedListener {
                val amount = it.toString().toDoubleOrNull() ?: 0.0

                when {
                    amount > walletBalance -> {
                        warning.text = "Insufficient wallet balance (Available: ₹$walletBalance)"
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

                override fun onResponse(call: Call<PayKhataResponse>, response: Response<PayKhataResponse>) {
                    val body = response.body() ?: return

                    if (body.success) {

                        SessionManager.saveWalletBalance(this@CustomerKhataListActivity, body.wallet_balance)

                        AlertDialog.Builder(this@CustomerKhataListActivity)
                            .setTitle("Payment Successful")
                            .setMessage("Paid: ₹$amount\nNew Wallet Balance: ₹${body.wallet_balance}")
                            .setPositiveButton("OK", null)
                            .show()

                        loadAccounts()
                    } else {
                        Toast.makeText(this@CustomerKhataListActivity, body.message ?: "Error", Toast.LENGTH_LONG).show()
                    }
                }

                override fun onFailure(call: Call<PayKhataResponse>, t: Throwable) {
                    Toast.makeText(this@CustomerKhataListActivity, t.message, Toast.LENGTH_LONG).show()
                }
            })
    }
}
