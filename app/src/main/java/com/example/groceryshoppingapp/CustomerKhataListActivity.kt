package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.adapters.KhataAccountAdapter
import com.example.groceryshoppingapp.databinding.ActivityCustomerKhataListBinding
import com.example.groceryshoppingapp.models.KhataAccount
import com.example.groceryshoppingapp.models.KhataAccountsResponse
import com.example.groceryshoppingapp.models.WalletBalanceResponse
import com.example.groceryshoppingapp.network.ApiService
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
                showPaymentMethodDialog(acc) // ⭐ NEW FLOW
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

        api.getMyKhataAccounts(customerId).enqueue(object : Callback<KhataAccountsResponse> {
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
                Toast.makeText(this@CustomerKhataListActivity, t.message, Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun updateLastUpdated() {
        val sdf = SimpleDateFormat("hh:mm a", Locale.getDefault())
        binding.tvLastUpdated.text = "Updated: ${sdf.format(Date())}"
    }

    // ⭐ FIXED — REALTIME LISTENER NOW POPULATES shopId TOO
    private fun listenRealtime() {
        val customerId = SessionManager.getCustomerId(this) ?: return

        Firebase.firestore.collection("khata_accounts")
            .whereEqualTo("customer_id", customerId)
            .addSnapshotListener { snap, _ ->
                if (snap == null) return@addSnapshotListener

                accounts.clear()
                snap.documents.forEach { doc ->
                    val acc = doc.toObject(KhataAccount::class.java) ?: return@forEach

                    acc.shopName = doc.getString("shop_name") ?: acc.shopName ?: "Unknown Shop"

                    acc.shopId = doc.getString("shop_id") ?: acc.shopId  // ⭐ IMPORTANT FIX

                    accounts.add(acc)
                }

                adapter.notifyDataSetChanged()
                updateLastUpdated()
            }
    }

    // -------------------------------------------------------------------------
    // ⭐ Fetch LIVE WALLET BALANCE from backend
    // -------------------------------------------------------------------------
    private fun fetchWalletBalance(callback: (Double) -> Unit) {
        val userId = SessionManager.getCustomerId(this) ?: return

        api.getWalletBalance(userId).enqueue(object : Callback<WalletBalanceResponse> {

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

    // -------------------------------------------------------------------------
    // ⭐ PAYMENT METHOD DIALOG
    // -------------------------------------------------------------------------
    private fun showPaymentMethodDialog(acc: KhataAccount) {

        val options = arrayOf("Wallet", "UPI / Razorpay", "Cash Payment")

        AlertDialog.Builder(this)
            .setTitle("Choose Payment Method")
            .setItems(options) { _, which ->

                when (which) {

                    0 -> {
                        // Fetch live wallet balance before showing confirmation
                        fetchWalletBalance { balance ->
                            showWalletConfirmation(acc, balance)
                        }
                    }

                    1 -> Toast.makeText(this, "UPI Coming Soon", Toast.LENGTH_SHORT).show()

                    2 -> Toast.makeText(this, "Cash Payment Recorded", Toast.LENGTH_SHORT).show()
                }

            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // -------------------------------------------------------------------------
    // ⭐ WALLET CONFIRMATION DIALOG
    // -------------------------------------------------------------------------
    private fun showWalletConfirmation(acc: KhataAccount, walletBalance: Double) {

        val amountDue = acc.balance ?: 0.0

        AlertDialog.Builder(this)
            .setTitle("Confirm Wallet Payment")
            .setMessage(
                "Wallet Balance: ₹$walletBalance\n" +
                        "Amount to Pay: ₹$amountDue\n\n" +
                        "Do you want to continue?"
            )
            .setPositiveButton("Yes") { _, _ ->
                showAmountInputDialog(acc)
            }
            .setNegativeButton("No", null)
            .show()
    }

    // -------------------------------------------------------------------------
    // Ask user for amount to pay
    // -------------------------------------------------------------------------
    private fun showAmountInputDialog(acc: KhataAccount) {

        val input = EditText(this)
        input.hint = "Enter amount"
        input.inputType = android.text.InputType.TYPE_CLASS_NUMBER

        AlertDialog.Builder(this)
            .setTitle("Pay Due • ${acc.shopName}")
            .setMessage("Your due amount is ₹${acc.balance}")
            .setView(input)
            .setPositiveButton("Pay") { _, _ ->
                val amount = input.text.toString().toDoubleOrNull() ?: 0.0
                if (amount <= 0) {
                    Toast.makeText(this, "Enter valid amount", Toast.LENGTH_SHORT).show()
                } else {
                    payKhata(acc, amount)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // -------------------------------------------------------------------------
    // CALL BACKEND TO PAY USING WALLET
    // -------------------------------------------------------------------------
    private fun payKhata(acc: KhataAccount, amount: Double) {

        val request = PayKhataRequest(
            shop_id = acc.shopId ?: "",   // ⭐ FIXED: Now always correct
            customer_id = SessionManager.getCustomerId(this) ?: "",
            amount = amount
        )

        api.payKhataFromWallet(request).enqueue(object : Callback<PayKhataResponse> {

            override fun onResponse(call: Call<PayKhataResponse>, response: Response<PayKhataResponse>) {
                val body = response.body() ?: return

                if (body.success) {

                    // Update local wallet balance
                    SessionManager.saveWalletBalance(this@CustomerKhataListActivity, body.wallet_balance)

                    showPaymentSuccessDialog(amount, body.wallet_balance)

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

    // -------------------------------------------------------------------------
    // ⭐ PAYMENT SUCCESS POPUP
    // -------------------------------------------------------------------------
    private fun showPaymentSuccessDialog(amount: Double, newBalance: Double) {
        AlertDialog.Builder(this)
            .setTitle("Payment Successful")
            .setMessage("Paid: ₹$amount\nNew Wallet Balance: ₹$newBalance")
            .setPositiveButton("OK", null)
            .show()
    }
}
