//package com.example.groceryshoppingapp
//
//import android.app.AlertDialog
//import android.os.Bundle
//import android.os.Handler
//import android.view.View
//import android.widget.EditText
//import android.widget.Toast
//import androidx.appcompat.app.AppCompatActivity
//import androidx.recyclerview.widget.LinearLayoutManager
//import com.example.groceryshoppingapp.adapters.KhataTransactionAdapter
//import com.example.groceryshoppingapp.databinding.ActivityKhataCustomerDetailBinding
//import com.example.groceryshoppingapp.models.KhataAccount
//import com.example.groceryshoppingapp.models.KhataLedgerResponse
//import com.example.groceryshoppingapp.models.KhataTransaction
//import com.example.groceryshoppingapp.models.KhataTransactionRequest
//import com.example.groceryshoppingapp.network.ApiResponse
//import com.example.groceryshoppingapp.network.ApiService
//import com.example.groceryshoppingapp.network.RetrofitClient
//import com.example.groceryshoppingapp.utils.SessionManager
//import retrofit2.Call
//import retrofit2.Callback
//import retrofit2.Response
//import java.text.SimpleDateFormat
//import java.util.*
//
//class KhataCustomerDetailActivity : AppCompatActivity() {
//
//    private lateinit var binding: ActivityKhataCustomerDetailBinding
//    private lateinit var api: ApiService
//    private lateinit var account: KhataAccount
//
//    private lateinit var adapter: KhataTransactionAdapter
//    private val transactions = mutableListOf<KhataTransaction>()
//
//    private var isReadOnly = true
//
//    private val handler = Handler()
//
//    // Customer: auto-refresh every 4 sec
//    private val customerAutoRefreshRunnable = object : Runnable {
//        override fun run() {
//            if (isReadOnly) {  // customers only
//                loadLedger(false)
//                handler.postDelayed(this, 4000)
//            }
//        }
//    }
//
//    override fun onCreate(savedInstanceState: Bundle?) {
//        super.onCreate(savedInstanceState)
//        binding = ActivityKhataCustomerDetailBinding.inflate(layoutInflater)
//        setContentView(binding.root)
//
//        api = RetrofitClient.getInstance(this).create(ApiService::class.java)
//
//        account = intent.getParcelableExtra("account")
//            ?: return showFatalError("Missing account data")
//
//        isReadOnly = intent.getBooleanExtra("isReadOnly", true)
//
//        when (SessionManager.getRole(this)) {
//            "shopowner" -> isReadOnly = false
//            "customer" -> isReadOnly = true
//        }
//
//        setupRecycler()
//        setupButtons()
//        setupPullToRefresh()
//        bindHeader()
//
//        loadLedger(true)
//
//        // AUTO REFRESH (CUSTOMER only)
//        if (isReadOnly) {
//            handler.post(customerAutoRefreshRunnable)
//        }
//    }
//
//    private fun setupRecycler() {
//        adapter = KhataTransactionAdapter(transactions)
//        binding.rvTransactions.layoutManager = LinearLayoutManager(this)
//        binding.rvTransactions.adapter = adapter
//    }
//
//    private fun setupPullToRefresh() {
//        binding.swipeRefresh.setOnRefreshListener {
//            loadLedger(true)
//        }
//    }
//
//    private fun setupButtons() {
//        binding.btnBack.setOnClickListener { finish() }
//
//        if (isReadOnly) {
//            binding.layoutActions.visibility = View.GONE
//        } else {
//            binding.layoutActions.visibility = View.VISIBLE
//            binding.btnAddDebit.setOnClickListener { openAddDialog("debit") }
//            binding.btnAddCredit.setOnClickListener { openAddDialog("credit") }
//        }
//    }
//
//    private fun bindHeader() {
//        binding.tvCustomerName.text = account.customerName ?: "Customer"
//        binding.tvCustomerPhone.text = account.phone ?: "-"
//        updateBalanceUI(account.balance ?: 0.0)
//        updateLastUpdated()
//    }
//
//    private fun updateBalanceUI(balance: Double) {
//        val abs = kotlin.math.abs(balance)
//        binding.tvBalance.text = "₹${String.format("%.2f", abs)}"
//
//        binding.tvBalanceLabel.text = when {
//            balance > 0 -> if (isReadOnly) "You owe shop" else "Customer owes you"
//            balance < 0 -> if (isReadOnly) "Shop owes you" else "You owe customer"
//            else -> "All clear"
//        }
//    }
//
//    private fun updateLastUpdated() {
//        val sdf = SimpleDateFormat("hh:mm a", Locale.getDefault())
//        binding.tvLastUpdated.text = "Last updated: ${sdf.format(Date())}"
//    }
//
//    // -----------------------------------------
//    // MAIN LEDGER LOAD FUNCTION (Backend only)
//    // -----------------------------------------
//    private fun loadLedger(showLoader: Boolean) {
//
//        if (showLoader) binding.swipeRefresh.isRefreshing = true
//
//        val shopId = account.shopId ?: return
//        val customerId = account.customerId ?: return
//
//        api.getKhataLedger(shopId, customerId)
//            .enqueue(object : Callback<KhataLedgerResponse> {
//
//                override fun onResponse(
//                    call: Call<KhataLedgerResponse>,
//                    response: Response<KhataLedgerResponse>
//                ) {
//                    binding.swipeRefresh.isRefreshing = false
//
//                    if (!response.isSuccessful) return
//                    val body = response.body() ?: return
//
//                    val oldSize = transactions.size
//
//                    transactions.clear()
//                    body.transactions?.let { transactions.addAll(it) }
//                    adapter.notifyDataSetChanged()
//
//                    updateBalanceUI(body.account?.balance ?: 0.0)
//                    updateLastUpdated()
//
//                    // Auto-scroll for shopkeeper after adding
//                    if (!isReadOnly && transactions.size > oldSize) {
//                        binding.rvTransactions.scrollToPosition(transactions.size - 1)
//                    }
//                }
//
//                override fun onFailure(call: Call<KhataLedgerResponse>, t: Throwable) {
//                    binding.swipeRefresh.isRefreshing = false
//                    Toast.makeText(this@KhataCustomerDetailActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
//                }
//            })
//    }
//
//    // -----------------------------------------
//    // ADD TRANSACTION (Shop owner only)
//    // -----------------------------------------
//    private fun openAddDialog(type: String) {
//        val view = layoutInflater.inflate(R.layout.dialog_add_khata_transaction, null)
//        val etAmt = view.findViewById<EditText>(R.id.etAmount)
//        val etNote = view.findViewById<EditText>(R.id.etNote)
//
//        AlertDialog.Builder(this)
//            .setTitle(if (type == "debit") "Add Debit" else "Add Credit")
//            .setView(view)
//            .setPositiveButton("Save") { _, _ ->
//                val amount = etAmt.text.toString().toDoubleOrNull()
//                if (amount == null || amount <= 0) {
//                    Toast.makeText(this, "Invalid amount", Toast.LENGTH_SHORT).show()
//                    return@setPositiveButton
//                }
//                addTransaction(type, amount, etNote.text.toString())
//            }
//            .setNegativeButton("Cancel", null)
//            .show()
//    }
//
//    private fun addTransaction(type: String, amount: Double, note: String) {
//
//        val request = KhataTransactionRequest(
//            shop_id = account.shopId!!,
//            customer_id = account.customerId!!,
//            type = type,
//            amount = amount,
//            note = note
//        )
//
//        api.addKhataTransaction(request)
//            .enqueue(object : Callback<ApiResponse> {
//
//                override fun onResponse(call: Call<ApiResponse>, res: Response<ApiResponse>) {
//                    if (!res.isSuccessful) {
//                        Toast.makeText(this@KhataCustomerDetailActivity, "Failed", Toast.LENGTH_SHORT).show()
//                        return
//                    }
//
//                    Toast.makeText(this@KhataCustomerDetailActivity, "Saved", Toast.LENGTH_SHORT).show()
//
//                    // refresh immediately
//                    loadLedger(true)
//
//                    // refresh again after backend write completes
//                    handler.postDelayed({ loadLedger(false) }, 500)
//                }
//
//                override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
//                    Toast.makeText(this@KhataCustomerDetailActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
//                }
//            })
//    }
//
//    override fun onDestroy() {
//        super.onDestroy()
//        handler.removeCallbacks(customerAutoRefreshRunnable)
//    }
//
//    private fun showFatalError(msg: String): Nothing {
//        Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
//        finish()
//        throw IllegalStateException(msg)
//    }
//}

// ⭐ ONLY CHANGES ADDED ARE MARKED WITH COMMENTS ⭐

//package com.example.groceryshoppingapp
//
//import android.app.AlertDialog
//import android.os.Bundle
//import android.os.Handler
//import android.view.View
//import android.widget.EditText
//import android.widget.Toast
//import androidx.appcompat.app.AppCompatActivity
//import androidx.recyclerview.widget.LinearLayoutManager
//import com.example.groceryshoppingapp.adapters.KhataTransactionAdapter
//import com.example.groceryshoppingapp.databinding.ActivityKhataCustomerDetailBinding
//import com.example.groceryshoppingapp.models.KhataAccount
//import com.example.groceryshoppingapp.models.KhataLedgerResponse
//import com.example.groceryshoppingapp.models.KhataTransaction
//import com.example.groceryshoppingapp.models.KhataTransactionRequest
//import com.example.groceryshoppingapp.network.ApiResponse
//import com.example.groceryshoppingapp.network.ApiService
//import com.example.groceryshoppingapp.network.RetrofitClient
//import com.example.groceryshoppingapp.utils.SessionManager
//import retrofit2.Call
//import retrofit2.Callback
//import retrofit2.Response
//import java.text.SimpleDateFormat
//import java.util.*
//
//class KhataCustomerDetailActivity : AppCompatActivity() {
//
//    private lateinit var binding: ActivityKhataCustomerDetailBinding
//    private lateinit var api: ApiService
//    private lateinit var account: KhataAccount
//
//    private lateinit var adapter: KhataTransactionAdapter
//    private val transactions = mutableListOf<KhataTransaction>()
//
//    private var isReadOnly = true
//
//    private val handler = Handler()
//
//    private val customerAutoRefreshRunnable = object : Runnable {
//        override fun run() {
//            if (isReadOnly) {
//                loadLedger(false)
//                handler.postDelayed(this, 4000)
//            }
//        }
//    }
//
//    override fun onCreate(savedInstanceState: Bundle?) {
//        super.onCreate(savedInstanceState)
//        binding = ActivityKhataCustomerDetailBinding.inflate(layoutInflater)
//        setContentView(binding.root)
//
//        api = RetrofitClient.getInstance(this).create(ApiService::class.java)
//
//        account = intent.getParcelableExtra("account")
//            ?: return showFatalError("Missing account")
//
//        isReadOnly = intent.getBooleanExtra("isReadOnly", true)
//
//        when (SessionManager.getRole(this)) {
//            "shopowner" -> isReadOnly = false
//            "customer" -> isReadOnly = true
//        }
//
//        setupRecycler()
//        setupButtons()
//        setupPull()
//        bindHeader()
//
//        loadLedger(true)
//
//        if (isReadOnly) handler.post(customerAutoRefreshRunnable)
//    }
//
//    private fun setupRecycler() {
//        adapter = KhataTransactionAdapter(transactions)
//        binding.rvTransactions.layoutManager = LinearLayoutManager(this)
//        binding.rvTransactions.adapter = adapter
//    }
//
//    private fun setupPull() {
//        binding.swipeRefresh.setOnRefreshListener {
//            loadLedger(true)
//        }
//    }
//
//    private fun setupButtons() {
//        binding.btnBack.setOnClickListener {
//            // ⭐ RETURN UPDATED ACCOUNT SO SHOP NAME NEVER DISAPPEARS
//            val data = intent
//            data.putExtra("updated_account", account)
//            setResult(RESULT_OK, data)
//            finish()
//        }
//
//        if (isReadOnly) {
//            binding.layoutActions.visibility = View.GONE
//        } else {
//            binding.layoutActions.visibility = View.VISIBLE
//            binding.btnAddDebit.setOnClickListener { openAddDialog("debit") }
//            binding.btnAddCredit.setOnClickListener { openAddDialog("credit") }
//        }
//    }
//
//    private fun bindHeader() {
//        binding.tvCustomerName.text = account.customerName
//        binding.tvCustomerPhone.text = account.phone
//        updateBalanceUI(account.balance ?: 0.0)
//        updateLastUpdated()
//    }
//
//    private fun updateBalanceUI(balance: Double) {
//        val abs = kotlin.math.abs(balance)
//        binding.tvBalance.text = "₹${String.format("%.2f", abs)}"
//        binding.tvBalanceLabel.text = when {
//            balance > 0 -> if (isReadOnly) "You owe shop" else "Customer owes you"
//            balance < 0 -> if (isReadOnly) "Shop owes you" else "You owe customer"
//            else -> "All Clear"
//        }
//    }
//
//    private fun updateLastUpdated() {
//        val sdf = SimpleDateFormat("hh:mm a", Locale.getDefault())
//        binding.tvLastUpdated.text = "Last updated: ${sdf.format(Date())}"
//    }
//
//    private fun loadLedger(showLoader: Boolean) {
//        if (showLoader) binding.swipeRefresh.isRefreshing = true
//
//        val shopId = account.shopId ?: return
//        val customerId = account.customerId ?: return
//
//        api.getKhataLedger(shopId, customerId)
//            .enqueue(object : Callback<KhataLedgerResponse> {
//
//                override fun onResponse(
//                    call: Call<KhataLedgerResponse>,
//                    response: Response<KhataLedgerResponse>
//                ) {
//                    binding.swipeRefresh.isRefreshing = false
//                    if (!response.isSuccessful) return
//                    val body = response.body() ?: return
//
//                    // ⭐ UPDATE LOCAL ACCOUNT (fix shopName disappearing)
//                    account.balance = body.account?.balance
//                    account.shopName = body.account?.shopName
//
//                    transactions.clear()
//                    body.transactions?.let { transactions.addAll(it) }
//                    adapter.notifyDataSetChanged()
//
//                    updateBalanceUI(account.balance ?: 0.0)
//                    updateLastUpdated()
//                }
//
//                override fun onFailure(call: Call<KhataLedgerResponse>, t: Throwable) {
//                    binding.swipeRefresh.isRefreshing = false
//                }
//            })
//    }
//
//    private fun openAddDialog(type: String) {
//        val view = layoutInflater.inflate(R.layout.dialog_add_khata_transaction, null)
//        val amt = view.findViewById<EditText>(R.id.etAmount)
//        val note = view.findViewById<EditText>(R.id.etNote)
//
//        AlertDialog.Builder(this)
//            .setTitle(if (type == "debit") "Add Debit" else "Add Credit")
//            .setView(view)
//            .setPositiveButton("Save") { _, _ ->
//                val a = amt.text.toString().toDoubleOrNull()
//                if (a == null || a <= 0) {
//                    Toast.makeText(this, "Invalid amount", Toast.LENGTH_SHORT).show()
//                    return@setPositiveButton
//                }
//                addTransaction(type, a, note.text.toString())
//            }
//            .setNegativeButton("Cancel", null)
//            .show()
//    }
//
//    private fun addTransaction(type: String, amt: Double, note: String) {
//
//        val req = KhataTransactionRequest(
//            shop_id = account.shopId!!,
//            customer_id = account.customerId!!,
//            type = type,
//            amount = amt,
//            note = note
//        )
//
//        api.addKhataTransaction(req)
//            .enqueue(object : Callback<ApiResponse> {
//
//                override fun onResponse(call: Call<ApiResponse>, res: Response<ApiResponse>) {
//                    if (!res.isSuccessful) return
//
//                    Toast.makeText(this@KhataCustomerDetailActivity, "Saved", Toast.LENGTH_SHORT).show()
//
//                    loadLedger(true)
//                    handler.postDelayed({ loadLedger(false) }, 500)
//                }
//
//                override fun onFailure(call: Call<ApiResponse>, t: Throwable) { }
//            })
//    }
//
//    override fun onDestroy() {
//        super.onDestroy()
//        handler.removeCallbacks(customerAutoRefreshRunnable)
//    }
//
//    private fun showFatalError(msg: String): Nothing {
//        Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
//        finish()
//        throw IllegalStateException(msg)
//    }
//}

package com.example.groceryshoppingapp

import android.app.AlertDialog
import android.content.Intent
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

class KhataCustomerDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityKhataCustomerDetailBinding
    private lateinit var api: ApiService
    private lateinit var account: KhataAccount

    private lateinit var adapter: KhataTransactionAdapter
    private val transactions = mutableListOf<KhataTransaction>()

    private var isReadOnly = true
    private val handler = Handler()

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
            ?: return showFatalError("Missing account")

        isReadOnly = intent.getBooleanExtra("isReadOnly", true)

        when (SessionManager.getRole(this)) {
            "shopowner" -> isReadOnly = false
            "customer" -> isReadOnly = true
        }

        setupRecycler()
        setupButtons()
        setupPull()
        bindHeader()

        loadLedger(true)

        if (isReadOnly) handler.post(customerAutoRefreshRunnable)
    }

    private fun setupRecycler() {
        adapter = KhataTransactionAdapter(transactions)
        binding.rvTransactions.layoutManager = LinearLayoutManager(this)
        binding.rvTransactions.adapter = adapter
    }

    private fun setupPull() {
        binding.swipeRefresh.setOnRefreshListener {
            loadLedger(true)
        }
    }

    private fun setupButtons() {

        // ⭐ FIX — Return updated account to list screen
        binding.btnBack.setOnClickListener {
            val intent = Intent()
            intent.putExtra("updated_account", account)
            setResult(RESULT_OK, intent)
            finish()
        }

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
        val abs = kotlin.math.abs(balance)
        binding.tvBalance.text = "₹${String.format("%.2f", abs)}"

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

    // =============================
    // LOAD LEDGER (Backend only)
    // =============================
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

                    // ⭐ FIX — Keep account updated ALWAYS
                    account.balance = body.account?.balance
                    account.shopName = body.account?.shopName
                    account.customerName = body.account?.customerName
                    account.phone = body.account?.phone

                    transactions.clear()
                    body.transactions?.let { transactions.addAll(it) }
                    adapter.notifyDataSetChanged()

                    updateBalanceUI(account.balance ?: 0.0)
                    updateLastUpdated()
                }

                override fun onFailure(call: Call<KhataLedgerResponse>, t: Throwable) {
                    binding.swipeRefresh.isRefreshing = false
                }
            })
    }

    private fun openAddDialog(type: String) {
        val view = layoutInflater.inflate(R.layout.dialog_add_khata_transaction, null)
        val amt = view.findViewById<EditText>(R.id.etAmount)
        val note = view.findViewById<EditText>(R.id.etNote)

        AlertDialog.Builder(this)
            .setTitle(if (type == "debit") "Add Debit" else "Add Credit")
            .setView(view)
            .setPositiveButton("Save") { _, _ ->
                val a = amt.text.toString().toDoubleOrNull()
                if (a == null || a <= 0) {
                    Toast.makeText(this, "Invalid amount", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                addTransaction(type, a, note.text.toString())
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun addTransaction(type: String, amt: Double, note: String) {

        val req = KhataTransactionRequest(
            shop_id = account.shopId!!,
            customer_id = account.customerId!!,
            type = type,
            amount = amt,
            note = note
        )

        api.addKhataTransaction(req)
            .enqueue(object : Callback<ApiResponse> {

                override fun onResponse(call: Call<ApiResponse>, res: Response<ApiResponse>) {
                    if (!res.isSuccessful) return
                    Toast.makeText(this@KhataCustomerDetailActivity, "Saved", Toast.LENGTH_SHORT).show()

                    loadLedger(true)
                }

                override fun onFailure(call: Call<ApiResponse>, t: Throwable) {}
            })
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacks(customerAutoRefreshRunnable)
    }

    private fun showFatalError(msg: String): Nothing {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
        finish()
        throw IllegalStateException(msg)
    }
}
