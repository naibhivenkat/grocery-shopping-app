package com.example.groceryshoppingapp

import android.app.AlertDialog
import android.os.Bundle
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
import com.google.firebase.firestore.ListenerRegistration
import com.google.firebase.firestore.ktx.firestore
import com.google.firebase.ktx.Firebase
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class KhataCustomerDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityKhataCustomerDetailBinding
    private lateinit var api: ApiService
    private lateinit var account: KhataAccount
    private lateinit var adapter: KhataTransactionAdapter
    private val transactions = mutableListOf<KhataTransaction>()

    private var isReadOnly: Boolean = true // default: customer view

    private var txListener: ListenerRegistration? = null
    private var balanceListener: ListenerRegistration? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityKhataCustomerDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)

        api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        // Get account from intent, or fail
        account = intent.getParcelableExtra("account")
            ?: showFatalError("Invalid account data")

        // Initial read-only flag from intent
        isReadOnly = intent.getBooleanExtra("isReadOnly", true)

        // Override with session role (final authority)
        when (SessionManager.getRole(this)) {
            "shopowner" -> isReadOnly = false
            "customer"  -> isReadOnly = true
        }

        setupRecycler()
        setupButtons()
        bindHeader()

        // Initial fetch from backend
        loadLedger()

        // Live updates from Firestore
        listenToTransactions()
        listenToBalance()
    }

    private fun setupRecycler() {
        adapter = KhataTransactionAdapter(transactions)
        binding.rvTransactions.layoutManager = LinearLayoutManager(this)
        binding.rvTransactions.adapter = adapter
    }

    private fun setupButtons() {
        binding.btnBack.setOnClickListener { finish() }

        if (isReadOnly) {
            // Customer app -> hide action buttons
            binding.layoutActions.visibility = View.GONE
        } else {
            // Shop owner -> can add debit / credit
            binding.layoutActions.visibility = View.VISIBLE
            binding.btnAddDebit.setOnClickListener { openAddTransactionDialog("debit") }
            binding.btnAddCredit.setOnClickListener { openAddTransactionDialog("credit") }
        }
    }

    private fun bindHeader() {
        binding.tvCustomerName.text = account.customerName ?: "Customer"
        binding.tvCustomerPhone.text = account.phone ?: "-"

        val bal = account.balance ?: 0.0
        updateBalanceUI(bal)
    }

    private fun updateBalanceUI(balance: Double) {
        binding.tvBalance.text = "₹${String.format("%.2f", balance)}"

        binding.tvBalanceLabel.text = when {
            balance > 0 ->
                if (isReadOnly) "You owe shop" else "Customer owes you"
            balance < 0 ->
                if (isReadOnly) "Shop owes you" else "You owe customer"
            else -> "All Clear"
        }
    }

    private fun loadLedger() {
        val shopId = account.shopId ?: return
        val customerId = account.customerId ?: return

        api.getKhataLedger(shopId, customerId)
            .enqueue(object : Callback<KhataLedgerResponse> {
                override fun onResponse(
                    call: Call<KhataLedgerResponse>,
                    response: Response<KhataLedgerResponse>
                ) {
                    if (!response.isSuccessful) return
                    val body = response.body() ?: return

                    // Backend transactions
                    transactions.clear()
                    body.transactions?.let { transactions.addAll(it) }
                    adapter.notifyDataSetChanged()

                    val bal = body.account?.balance ?: 0.0
                    updateBalanceUI(bal)
                }

                override fun onFailure(call: Call<KhataLedgerResponse>, t: Throwable) {
                    Toast.makeText(
                        this@KhataCustomerDetailActivity,
                        "Error: ${t.message}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            })
    }

    private fun listenToTransactions() {
        val shopId = account.shopId ?: return
        val customerId = account.customerId ?: return

        txListener = Firebase.firestore.collection("khata_transactions")
            .whereEqualTo("shop_id", shopId)
            .whereEqualTo("customer_id", customerId)
            .orderBy("created_at")
            .addSnapshotListener { snapshot, error ->

                if (error != null) {
                    // DO NOT clear the list
                    return@addSnapshotListener
                }

                if (snapshot == null || snapshot.isEmpty) {
                    // DO NOT clear on null snapshot
                    return@addSnapshotListener
                }

                transactions.clear()
                for (doc in snapshot.documents) {
                    doc.toObject(KhataTransaction::class.java)?.let { transactions.add(it) }
                }
                adapter.notifyDataSetChanged()
            }
    }

    private fun listenToBalance() {
        val shopId = account.shopId ?: return
        val customerId = account.customerId ?: return
        val docId = "${shopId}_${customerId}"

        balanceListener = Firebase.firestore.collection("khata_accounts")
            .document(docId)
            .addSnapshotListener { snapshot, error ->
                if (error != null || snapshot == null) return@addSnapshotListener
                val newBalance = snapshot.getDouble("balance") ?: 0.0
                updateBalanceUI(newBalance)
            }
    }

    private fun openAddTransactionDialog(type: String) {
        val view = layoutInflater.inflate(R.layout.dialog_add_khata_transaction, null)
        val etAmount = view.findViewById<EditText>(R.id.etAmount)
        val etNote = view.findViewById<EditText>(R.id.etNote)

        val title = if (type == "debit")
            "Add Debit (customer owes more)"
        else
            "Add Credit (customer pays)"

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

                    // Optional: refresh from backend (Firestore listener will also update)
                    loadLedger()
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

    private fun showFatalError(msg: String): Nothing {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
        finish()
        throw IllegalStateException(msg)
    }

    override fun onDestroy() {
        super.onDestroy()
        txListener?.remove()
        balanceListener?.remove()
    }
}
