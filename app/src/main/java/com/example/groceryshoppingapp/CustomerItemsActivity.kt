package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.ItemAdapter
import com.example.groceryshoppingapp.models.GetItemsResponse
import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.android.material.floatingactionbutton.FloatingActionButton
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class CustomerItemsActivity : AppCompatActivity() {

    private lateinit var recyclerView: RecyclerView
    private lateinit var itemAdapter: ItemAdapter
    private lateinit var fabCart: FloatingActionButton

    private var shopId: String? = null
    private var customerId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_customer_items)

        recyclerView = findViewById(R.id.recyclerView)
        fabCart = findViewById(R.id.fabCart)

        // Load session data
        customerId = SessionManager.getCustomerId(this)
        shopId = intent.getStringExtra("SHOP_ID") ?: SessionManager.getShopId(this)

        if (customerId.isNullOrEmpty()) {
            Toast.makeText(this, "Session expired. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        if (shopId.isNullOrEmpty()) {
            Toast.makeText(this, "Please select a shop first.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, ShopSelectionActivity::class.java))
            finish()
            return
        }

        recyclerView.layoutManager = LinearLayoutManager(this)
        // ⚡ Updated adapter to match ItemAdapter(Item, String) lambda
        itemAdapter = ItemAdapter { item, quantityWithUnit ->
            val sid = shopId ?: return@ItemAdapter
            // Use quantityWithUnit string from adapter
            CartManager.addToCart(item, sid, quantity = 1.0, unit = quantityWithUnit)
            Toast.makeText(this, "${item.name} ($quantityWithUnit) added to cart", Toast.LENGTH_SHORT).show()
            Log.d("CustomerItems", "Added to cart → shopId=$sid, item=${item.name}, unit=$quantityWithUnit")
        }
        recyclerView.adapter = itemAdapter

        fetchItems()

        fabCart.setOnClickListener {
            Log.d("CustomerItems", "Opening CartActivity with shopId=$shopId")
            val intent = Intent(this, CartActivity::class.java)
            intent.putExtra("SHOP_ID", shopId)
            startActivity(intent)
        }
    }

    private fun fetchItems() {
        val sid = shopId ?: return

        val apiService = RetrofitClient.getInstance(this).create(ApiService::class.java)
        val call = apiService.getItems(sid)

        call.enqueue(object : Callback<GetItemsResponse> {
            override fun onResponse(
                call: Call<GetItemsResponse>,
                response: Response<GetItemsResponse>
            ) {
                if (response.isSuccessful) {
                    val itemsResponse = response.body()
                    val items = itemsResponse?.items ?: emptyList()

                    itemAdapter.updateItems(items)
                    Log.d("CustomerItems", "Loaded ${items.size} items from API for shopId=$sid")
                } else {
                    Toast.makeText(this@CustomerItemsActivity, "Failed to load items", Toast.LENGTH_SHORT).show()
                    Log.e("CustomerItems", "Error: ${response.errorBody()?.string()}")
                }
            }

            override fun onFailure(call: Call<GetItemsResponse>, t: Throwable) {
                Toast.makeText(this@CustomerItemsActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
                Log.e("CustomerItems", "Network error", t)
            }
        })
    }
}
