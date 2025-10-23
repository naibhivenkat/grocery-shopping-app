package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.AdapterView
import android.widget.Button
import android.widget.ListView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.adapters.ShopAdapter
import com.example.groceryshoppingapp.models.Shop
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ShopSelectionActivity : AppCompatActivity() {

    private lateinit var shopListView: ListView
    private var shops: List<Shop> = emptyList()
    private var customerId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_shop_selection)

        shopListView = findViewById(R.id.shop_list_view)
        customerId = SessionManager.getCustomerId(this)

        if (customerId.isNullOrEmpty()) {
            Toast.makeText(this, "Invalid customer ID", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        // 🔑 Fetch shops from backend API
        fetchShopsFromServer()

        // ✅ Buttons
        val btnHome: Button = findViewById(R.id.btn_home)
        val btnBack: Button = findViewById(R.id.btn_back)
        val btnCart: Button = findViewById(R.id.btn_cart)

        btnHome.setOnClickListener {
            startActivity(Intent(this, CustomerHomeActivity::class.java))
            finish()
        }

        btnBack.setOnClickListener { finish() }

        btnCart.setOnClickListener {
            val allCarts = CartManager.getAllCarts().filterValues { it.isNotEmpty() }

            if (allCarts.isEmpty()) {
                Toast.makeText(this, "Cart is empty", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val shopIdList = allCarts.keys.toList()
            val shopNames = shopIdList.map { shopId ->
                shops.find { it.id == shopId }?.name ?: "Shop $shopId"
            }.toTypedArray()

            AlertDialog.Builder(this)
                .setTitle("Select Cart (Shop)")
                .setItems(shopNames) { _, index ->
                    val selectedShopId = shopIdList[index]
                    val selectedCartItems = allCarts[selectedShopId] ?: emptyList()
                    startActivity(Intent(this, CartActivity::class.java).apply {
                        putExtra("customer_id", customerId)
                        putExtra("shop_id", selectedShopId)
                        putParcelableArrayListExtra("cart_items", ArrayList(selectedCartItems))
                    })
                }
                .setNegativeButton("Cancel", null)
                .show()
        }
    }

    private fun fetchShopsFromServer() {
        val apiService = RetrofitClient.getInstance(this).create(ApiService::class.java)

        apiService.getAllShops().enqueue(object : Callback<List<Shop>> {
            override fun onResponse(call: Call<List<Shop>>, response: Response<List<Shop>>) {
                if (response.isSuccessful && response.body() != null) {
                    shops = response.body()!!

                    val adapter = ShopAdapter(this@ShopSelectionActivity, shops)
                    shopListView.adapter = adapter

                    // ✅ Single click listener
                    shopListView.onItemClickListener = AdapterView.OnItemClickListener { _, _, position, _ ->
                        val selectedShop = shops[position]

                        AlertDialog.Builder(this@ShopSelectionActivity)
                            .setTitle("Confirm Shop")
                            .setMessage("Do you want to continue with '${selectedShop.name}'?")
                            .setPositiveButton("OK") { _, _ ->
                                // Save selected shop
                                SessionManager.setShopId(this@ShopSelectionActivity, selectedShop.id)
                                SessionManager.setShopInfo(this@ShopSelectionActivity, selectedShop.id, selectedShop.name)

                                // Navigate to shop items
                                startActivity(Intent(this@ShopSelectionActivity, ShopItemsActivity::class.java).apply {
                                    putExtra("SHOP_ID", selectedShop.id)
                                    putExtra("SHOP_NAME", selectedShop.name)
                                    putExtra("customer_id", customerId)
                                })
                            }
                            .setNegativeButton("Cancel", null)
                            .show()
                    }

                } else {
                    Toast.makeText(this@ShopSelectionActivity, "Failed to load shops", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<List<Shop>>, t: Throwable) {
                Toast.makeText(this@ShopSelectionActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }
}
