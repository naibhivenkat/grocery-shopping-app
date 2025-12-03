package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.adapters.KhataAccountAdapter
import com.example.groceryshoppingapp.databinding.ActivityShopKhataListBinding
import com.example.groceryshoppingapp.models.AppUser
import com.example.groceryshoppingapp.models.KhataAccount
import com.example.groceryshoppingapp.models.KhataAccountsResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ShopKhataListActivity : AppCompatActivity() {

    private lateinit var binding: ActivityShopKhataListBinding
    private lateinit var api: ApiService
    private val accounts = mutableListOf<KhataAccount>()
    private lateinit var adapter: KhataAccountAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityShopKhataListBinding.inflate(layoutInflater)
        setContentView(binding.root)

        api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        adapter = KhataAccountAdapter(accounts) { acc ->
            val intent = Intent(this, KhataCustomerDetailActivity::class.java)
            intent.putExtra("account", acc)
            intent.putExtra("isReadOnly", false)  // shop owner editable
            startActivity(intent)
        }

        binding.rvKhataCustomers.layoutManager = LinearLayoutManager(this)
        binding.rvKhataCustomers.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnCreateKhata.setOnClickListener { openSelectCustomerScreen() }

        binding.swipeRefresh.setOnRefreshListener {
            loadAccounts()
        }

        loadAccounts()
    }

    private fun loadAccounts() {
        binding.swipeRefresh.isRefreshing = true

        val shopId = SessionManager.getShopId(this)
        if (shopId.isNullOrEmpty()) {
            Toast.makeText(this, "No shopId found", Toast.LENGTH_SHORT).show()
            binding.swipeRefresh.isRefreshing = false
            return
        }

        api.getKhataCustomers(shopId).enqueue(object : Callback<KhataAccountsResponse> {
            override fun onResponse(
                call: Call<KhataAccountsResponse>,
                response: Response<KhataAccountsResponse>
            ) {
                binding.swipeRefresh.isRefreshing = false

                if (!response.isSuccessful) {
                    Toast.makeText(
                        this@ShopKhataListActivity,
                        "Failed to load",
                        Toast.LENGTH_SHORT
                    ).show()
                    return
                }

                val body = response.body()
                accounts.clear()

                body?.accounts?.let { list ->
                    list.forEach { acc ->
                        acc.shopName = acc.shopName ?: "Unknown Shop"
                        accounts.add(acc)
                    }
                }
                adapter.notifyDataSetChanged()

                binding.tvTotalCustomers.text = "Customers: ${accounts.size}"
                val totalDue = accounts.sumOf { it.balance ?: 0.0 }
                binding.tvTotalDue.text = "Total Due: ₹${String.format("%.2f", totalDue)}"
            }

            override fun onFailure(call: Call<KhataAccountsResponse>, t: Throwable) {
                binding.swipeRefresh.isRefreshing = false
                Toast.makeText(
                    this@ShopKhataListActivity,
                    "Error: ${t.message}",
                    Toast.LENGTH_SHORT
                ).show()
            }
        })
    }

    private fun openSelectCustomerScreen() {
        val intent = Intent(this, ShopOwnerSelectCustomerActivity::class.java)
        startActivityForResult(intent, 200)
    }

    override fun onActivityResult(reqCode: Int, resCode: Int, data: Intent?) {
        super.onActivityResult(reqCode, resCode, data)
        if (reqCode == 200 && resCode == RESULT_OK) {
            val customer = data?.getParcelableExtra<AppUser>("customer") ?: return
            createKhata(customer)
        }
    }

    private fun createKhata(customer: AppUser) {
        val shopId = SessionManager.getShopId(this)
        if (shopId.isNullOrEmpty()) {
            Toast.makeText(this, "No shopId found", Toast.LENGTH_SHORT).show()
            return
        }

        val customerId = customer.customerId ?: customer.id ?: ""
        val customerName = customer.fullName ?: ""
        val phone = customer.phone ?: ""

        val payload = mapOf(
            "shop_id" to shopId,
            "customer_id" to customerId,
            "customer_name" to customerName,
            "phone" to phone
        )

        api.createKhataLedger(payload).enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(
                call: Call<Map<String, Any>>,
                response: Response<Map<String, Any>>
            ) {
                if (!response.isSuccessful) {
                    Toast.makeText(
                        this@ShopKhataListActivity,
                        "Failed to create",
                        Toast.LENGTH_SHORT
                    ).show()
                    return
                }

                Toast.makeText(
                    this@ShopKhataListActivity,
                    "Khata Created Successfully",
                    Toast.LENGTH_SHORT
                ).show()
                loadAccounts()
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                Toast.makeText(
                    this@ShopKhataListActivity,
                    "Error: ${t.message}",
                    Toast.LENGTH_SHORT
                ).show()
            }
        })
    }
}
