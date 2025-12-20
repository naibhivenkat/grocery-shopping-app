package com.example.groceryshoppingapp

import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.adapters.ShopWalletTransactionAdapter
import com.example.groceryshoppingapp.models.WalletTransaction
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.network.ShopWalletBalanceResponse
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.android.material.chip.ChipGroup
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ShopOwnerWalletActivity : AppCompatActivity() {

    private lateinit var tvBalance: TextView
    private lateinit var rvTransactions: androidx.recyclerview.widget.RecyclerView
    private lateinit var chipGroup: ChipGroup

    private val transactions = mutableListOf<WalletTransaction>()
    private val filteredList = mutableListOf<WalletTransaction>()

    private lateinit var adapter: ShopWalletTransactionAdapter
    private lateinit var api: ApiService
    private var shopId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_shop_wallet)

        api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        shopId = SessionManager.getShopId(this)

        tvBalance = findViewById(R.id.tvBalanceShop)
        rvTransactions = findViewById(R.id.rvShopTransactions)
        chipGroup = findViewById(R.id.chipShopFilterGroup)

        val layoutBack = findViewById<LinearLayout>(R.id.layoutBackShopWallet)
        layoutBack.setOnClickListener { finish() }

        adapter = ShopWalletTransactionAdapter(filteredList)
        rvTransactions.layoutManager = LinearLayoutManager(this)
        rvTransactions.adapter = adapter

        setupFilterListeners()
        fetchWalletBalance()
        fetchTransactions()
    }

    private fun setupFilterListeners() {
        chipGroup.setOnCheckedStateChangeListener { _, _ -> applyFilter() }
    }

    private fun applyFilter() {
        val selectedId = chipGroup.checkedChipId
        filteredList.clear()

        when (selectedId) {
            R.id.chipShopIncome ->
                filteredList.addAll(transactions.filter { it.type.equals("Order Income", true) })

            R.id.chipShopRefund ->
                filteredList.addAll(transactions.filter {
                    it.type.equals("Refund", true) || it.type.equals("Partial Refund", true)
                })

            else -> filteredList.addAll(transactions)
        }

        adapter.notifyDataSetChanged()
    }

    private fun fetchWalletBalance() {
        api.getShopWalletBalance(shopId!!).enqueue(object : Callback<ShopWalletBalanceResponse> {

            override fun onResponse(
                call: Call<ShopWalletBalanceResponse>,
                resp: Response<ShopWalletBalanceResponse>
            ) {
                val bal = resp.body()?.balance ?: 0.0
                tvBalance.text = "₹$bal"
            }

            override fun onFailure(call: Call<ShopWalletBalanceResponse>, t: Throwable) {
                Toast.makeText(this@ShopOwnerWalletActivity, "Error loading balance", Toast.LENGTH_SHORT).show()
            }
        })
    }


    private fun fetchTransactions() {
        api.getShopWalletTransactions(shopId!!).enqueue(object : Callback<List<WalletTransaction>> {

            override fun onResponse(call: Call<List<WalletTransaction>>, resp: Response<List<WalletTransaction>>) {
                transactions.clear()
                resp.body()?.let { transactions.addAll(it) }
                applyFilter()
            }

            override fun onFailure(call: Call<List<WalletTransaction>>, t: Throwable) {
                Toast.makeText(this@ShopOwnerWalletActivity, "Failed to load transactions", Toast.LENGTH_SHORT).show()
            }
        })
    }
}
