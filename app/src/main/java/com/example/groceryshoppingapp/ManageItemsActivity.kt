package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.ImageButton
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.ItemAdapter
import com.example.groceryshoppingapp.models.GetItemsResponse
import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.utils.SessionManager
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.network.ApiService
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ManageItemsActivity : AppCompatActivity() {

    private lateinit var itemAdapter: ItemAdapter
    private lateinit var itemList: MutableList<Item>
    private lateinit var rvItems: RecyclerView
    private lateinit var btnAddItem: Button
    private lateinit var btnBack: ImageButton
    private lateinit var btnRefresh: ImageButton

    private val api = RetrofitClient.getInstance(this).create(ApiService::class.java)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_manage_items)

        rvItems = findViewById(R.id.rv_items)
        btnAddItem = findViewById(R.id.btn_add_item)
        btnBack = findViewById(R.id.btn_back)
        btnRefresh = findViewById(R.id.btn_refresh)

        itemList = mutableListOf()
        itemAdapter = ItemAdapter(itemList) { selectedItem ->
            val intent = Intent(this, UpdateItemActivity::class.java)
            intent.putExtra("item", selectedItem)  // FIXED LINE
            startActivity(intent)
        }


        rvItems.layoutManager = LinearLayoutManager(this)
        rvItems.adapter = itemAdapter

        fetchItems()

        btnAddItem.setOnClickListener {
            val intent = Intent(this, AddItemsActivity::class.java)
            startActivity(intent)
        }

        btnRefresh.setOnClickListener {
            finish()
            startActivity(intent) // Clean re-load
        }

        btnBack.setOnClickListener {
            onBackPressed()
        }
    }

    private fun fetchItems() {
        val shopId = SessionManager.getShopId(this)
        if (shopId.isNullOrEmpty()) {
            Toast.makeText(this, "Shop ID not found. Please create a shop first.", Toast.LENGTH_SHORT).show()
            return
        }

        val token = SessionManager.getAuthToken(this)
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "Auth token missing. Please login again.", Toast.LENGTH_SHORT).show()
            return
        }

        val authHeader = "Bearer $token"
        Log.d("ManageItemsActivity", "Fetching items for shopId: $shopId with token: $token")

        api.getItems(authHeader, shopId).enqueue(object : Callback<GetItemsResponse> {
            override fun onResponse(call: Call<GetItemsResponse>, response: Response<GetItemsResponse>) {
                if (response.isSuccessful) {
                    val body = response.body()
                    val items = body?.items ?: emptyList()
                    itemList.clear()
                    itemList.addAll(items)
                    itemAdapter.notifyDataSetChanged()
                } else {
                    Toast.makeText(this@ManageItemsActivity, "Failed to load items: ${response.code()}", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<GetItemsResponse>, t: Throwable) {
                Toast.makeText(this@ManageItemsActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })

    }
    
    override fun onResume() {
        super.onResume()
        fetchItems()
    }
}
