package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.ItemAdapter
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.android.material.floatingactionbutton.FloatingActionButton
import android.util.Log
import com.example.groceryshoppingapp.models.GetItemsResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient

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
        //customerId = SessionManager.getCustomerId(this)
        //shopId = SessionManager.getShopId(this)

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
        itemAdapter = ItemAdapter { item -> addToCart(item) }
        recyclerView.adapter = itemAdapter

        fetchItems()

        fabCart.setOnClickListener {
            Log.d("CustomerItems", "Opening CartActivity with shopId=$shopId")
            val intent = Intent(this, CartActivity::class.java)
            intent.putExtra("SHOP_ID", shopId) // ✅ pass shopId to CartActivity
            startActivity(intent)
        }
    }

    private fun fetchItems() {
        val sid = shopId ?: return

        val apiservice = RetrofitClient.getInstance(this).create(ApiService::class.java)
        val call = apiservice.getItems(shopId!!)
        call.enqueue(object : retrofit2.Callback<GetItemsResponse> {
            override fun onResponse(
                call: retrofit2.Call<GetItemsResponse>,
                response: retrofit2.Response<GetItemsResponse>
            ) {
                if (response.isSuccessful) {
                    val itemsResponse = response.body()
                    val items = itemsResponse?.items ?: emptyList()

                    itemAdapter.updateItems(items)
                    Log.d("CustomerItems", "Loaded ${items.size} items from API for shopId=$sid")
                } else {
                    Toast.makeText(
                        this@CustomerItemsActivity,
                        "Failed to load items",
                        Toast.LENGTH_SHORT
                    ).show()
                    Log.e("CustomerItems", "Error: ${response.errorBody()?.string()}")
                }
            }

            override fun onFailure(call: retrofit2.Call<GetItemsResponse>, t: Throwable) {
                Toast.makeText(
                    this@CustomerItemsActivity,
                    "Error: ${t.message}",
                    Toast.LENGTH_SHORT
                ).show()
                Log.e("CustomerItems", "Network error", t)
            }
        })
    }


    private fun addToCart(item: Item) {
        val sid = shopId ?: return
        CartManager.addToCart(item, sid)
        Toast.makeText(this, "${item.name} added to cart", Toast.LENGTH_SHORT).show()
        Log.d("CustomerItems", "Added to cart → shopId=$sid, item=${item.name}")
    }
}
