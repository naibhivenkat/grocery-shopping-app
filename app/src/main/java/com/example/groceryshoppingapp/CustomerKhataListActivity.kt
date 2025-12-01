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

import com.google.firebase.firestore.ListenerRegistration
import com.google.firebase.firestore.ktx.firestore
import com.google.firebase.ktx.Firebase
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class CustomerKhataListActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCustomerKhataListBinding
    private lateinit var api: ApiService
    private val accounts = mutableListOf<KhataAccount>()
    private lateinit var adapter: KhataAccountAdapter

    private var accountsListener: ListenerRegistration? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityCustomerKhataListBinding.inflate(layoutInflater)
        setContentView(binding.root)

        api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        adapter = KhataAccountAdapter(accounts) { acc ->
            val intent = Intent(this, KhataCustomerDetailActivity::class.java)
            intent.putExtra("account", acc)
            intent.putExtra("isReadOnly", true)
            startActivity(intent)
        }

        binding.rvKhataList.layoutManager = LinearLayoutManager(this)
        binding.rvKhataList.adapter = adapter

        loadMyAccounts()
        listenToMyAccounts()
    }

    private fun loadMyAccounts() {
        val customerId = SessionManager.getCustomerId(this)
        if (customerId.isNullOrEmpty()) {
            Toast.makeText(this, "Not logged in", Toast.LENGTH_SHORT).show()
            return
        }

        api.getMyKhataAccounts(customerId)
            .enqueue(object : Callback<KhataAccountsResponse> {
                override fun onResponse(
                    call: Call<KhataAccountsResponse>,
                    response: Response<KhataAccountsResponse>
                ) {
                    if (!response.isSuccessful) return
                    accounts.clear()

                    response.body()?.accounts?.let { list ->
                        list.forEach { acc ->
                            // FIX: ensure IDs are present
                            if (acc.docId != null) {
                                val parts = acc.docId!!.split("_")
                                if (parts.size == 2) {
                                    acc.shopId = parts[0]
                                    acc.customerId = parts[1]
                                }
                            }
                            accounts.add(acc)
                        }
                    }
                    adapter.notifyDataSetChanged()
                }

                override fun onFailure(call: Call<KhataAccountsResponse>, t: Throwable) {
                    Toast.makeText(this@CustomerKhataListActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }

    private fun listenToMyAccounts() {
        val customerId = SessionManager.getCustomerId(this) ?: return

        accountsListener = Firebase.firestore.collection("khata_accounts")
            .whereEqualTo("customer_id", customerId)
            .addSnapshotListener { snapshot, error ->
                if (error != null || snapshot == null) return@addSnapshotListener

                accounts.clear()
                for (doc in snapshot.documents) {
                    val acc = doc.toObject(KhataAccount::class.java)
                    if (acc != null) {

                        acc.docId = doc.id

                        // FIX: recover missing shopId / customerId
                        val parts = doc.id.split("_")
                        if (parts.size == 2) {
                            acc.shopId = parts[0]
                            acc.customerId = parts[1]
                        }

                        accounts.add(acc)
                    }
                }
                adapter.notifyDataSetChanged()
            }
    }

    override fun onDestroy() {
        super.onDestroy()
        accountsListener?.remove()
    }
}
