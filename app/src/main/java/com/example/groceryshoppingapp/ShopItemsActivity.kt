package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.TextView
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
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ShopItemsActivity : AppCompatActivity() {

    private lateinit var itemsRecyclerView: RecyclerView
    private lateinit var btnGoToCart: Button
    private lateinit var btnHome: Button
    private lateinit var btnBackToShopList: Button
    private lateinit var adapter: ItemAdapter
    private lateinit var shopTitleText: TextView

    private var shopId: String? = null
    private var shopName: String = ""
    private val items = mutableListOf<Item>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_shop_items)

        itemsRecyclerView = findViewById(R.id.rv_shop_items)
        btnGoToCart = findViewById(R.id.btn_go_to_cart)
        btnBackToShopList = findViewById(R.id.btn_back_to_shop_list)
        btnHome = findViewById(R.id.btn_home)
        shopTitleText = findViewById(R.id.tv_shop_title)

        shopId = intent.getStringExtra("SHOP_ID")
        shopName = intent.getStringExtra("SHOP_NAME") ?: ""

        val customerId = SessionManager.getCustomerId(this)

        if (shopId.isNullOrEmpty() || customerId.isNullOrEmpty()) {
            Toast.makeText(this, "Invalid session or shop. Please login again.", Toast.LENGTH_SHORT).show()
            Log.e("ShopItemsActivity", "Invalid shopId=$shopId or customerId=$customerId")
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        shopTitleText.text = "Items in $shopName"

        // ⚡ Updated lambda to split quantityWithUnit into Double + unit
        adapter = ItemAdapter(items) { item, quantityWithUnit ->
            val parts = quantityWithUnit.split(" ")
            val qty = parts.getOrNull(0)?.toDoubleOrNull() ?: 1.0
            val unit = parts.getOrNull(1) ?: "pcs"

            Log.d("ShopItemsActivity", "Adding item=${item.name}, qty=$qty, unit=$unit, shopId=$shopId")
            CartManager.addToCart(item, shopId!!, qty, unit)
            Toast.makeText(this, "${item.name} ($qty $unit) added to cart", Toast.LENGTH_SHORT).show()
        }

        itemsRecyclerView.layoutManager = LinearLayoutManager(this)
        itemsRecyclerView.adapter = adapter

        fetchItemsFromBackend(shopId!!)

        btnGoToCart.setOnClickListener {
            Log.d("ShopItemsActivity", "Navigating to CartActivity with shopId=$shopId")
            val intent = Intent(this, CartActivity::class.java)
            intent.putExtra("SHOP_ID", shopId)
            startActivity(intent)
        }

        btnHome.setOnClickListener {
            startActivity(Intent(this, CustomerHomeActivity::class.java))
            finish()
        }

        btnBackToShopList.setOnClickListener {
            startActivity(Intent(this, ShopSelectionActivity::class.java))
            finish()
        }
    }

    private fun fetchItemsFromBackend(shopId: String) {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        api.getItems(shopId).enqueue(object : Callback<GetItemsResponse> {
            override fun onResponse(call: Call<GetItemsResponse>, response: Response<GetItemsResponse>) {
                if (response.isSuccessful) {
                    val fetchedItems = response.body()?.items ?: emptyList()
                    Log.d("ShopItemsActivity", "Fetched ${fetchedItems.size} items for shopId=$shopId")
                    items.clear()
                    items.addAll(fetchedItems)
                    adapter.notifyDataSetChanged()
                } else {
                    Log.e("ShopItemsActivity", "Failed to load items: ${response.code()}")
                    Toast.makeText(this@ShopItemsActivity, "Failed to load items", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<GetItemsResponse>, t: Throwable) {
                Log.e("ShopItemsActivity", "Error fetching items: ${t.message}")
                Toast.makeText(this@ShopItemsActivity, "Error: ${t.message}", Toast.LENGTH_LONG).show()
            }
        })
    }
}
