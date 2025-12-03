package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.adapters.KhataAccountAdapter
import com.example.groceryshoppingapp.databinding.ActivityCustomerKhataListBinding
import com.example.groceryshoppingapp.models.KhataAccount
import com.example.groceryshoppingapp.models.KhataAccountsResponse
import com.example.groceryshoppingapp.network.ApiService
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
        adapter = KhataAccountAdapter(accounts) { acc ->
            val intent = Intent(this, KhataCustomerDetailActivity::class.java)
            intent.putExtra("account", acc)
            intent.putExtra("isReadOnly", true)
            startActivity(intent)
        }
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
                    accounts.add(acc)
                }
                adapter.notifyDataSetChanged()
                updateLastUpdated()
            }
    }
}
