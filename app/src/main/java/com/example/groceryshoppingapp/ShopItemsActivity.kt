package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.ItemAdapter
import com.example.groceryshoppingapp.models.GetItemsResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.models.Item
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
    private val items = mutableListOf<Item>()  // 🔄 Mutable list for live updates

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_shop_items)

        // Initialize views
        itemsRecyclerView = findViewById(R.id.rv_shop_items)
        btnGoToCart = findViewById(R.id.btn_go_to_cart)
        btnBackToShopList = findViewById(R.id.btn_back_to_shop_list)
        btnHome = findViewById(R.id.btn_home)
        shopTitleText = findViewById(R.id.tv_shop_title)

        // Retrieve from intent
        shopId = intent.getStringExtra("SHOP_ID")
        shopName = intent.getStringExtra("SHOP_NAME") ?: ""

        val customerId = SessionManager.getCustomerId(this)

        if (shopId.isNullOrEmpty() || customerId.isNullOrEmpty()) {
            Toast.makeText(this, "Invalid session or shop. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        // Save selected shop to session
        SessionManager.setShopInfo(this, shopId.toString(), shopName)

        shopTitleText.text = "Items in $shopName"

        // Setup adapter
        adapter = ItemAdapter(items) { item ->
            CartManager.addToCart(item, shopId!!)
            Toast.makeText(this, "${item.name} added to cart for Shop #$shopId", Toast.LENGTH_SHORT).show()
        }
        itemsRecyclerView.layoutManager = LinearLayoutManager(this)
        itemsRecyclerView.adapter = adapter

        // Load items from backend
        fetchItemsFromBackend(shopId!!)

        // Button click listeners
        btnGoToCart.setOnClickListener {
            val intent = Intent(this, CartActivity::class.java)
            intent.putParcelableArrayListExtra("cart_items", ArrayList(CartManager.getCart(shopId!!)))
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
        val token = SessionManager.getAuthToken(this)
        if (token.isNullOrEmpty()) {
            Toast.makeText(this, "Auth token missing. Please login again.", Toast.LENGTH_SHORT).show()
            return
        }

        val authHeader = "Bearer $token"
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        api.getItemsForShop(authHeader, shopId).enqueue(object : Callback<GetItemsResponse> {
            override fun onResponse(call: Call<GetItemsResponse>, response: Response<GetItemsResponse>) {
                if (response.isSuccessful) {
                    val fetchedItems = response.body()?.items ?: emptyList()
                    items.clear()
                    items.addAll(fetchedItems)
                    adapter.notifyDataSetChanged()
                } else {
                    Toast.makeText(this@ShopItemsActivity, "Failed to load items: ${response.code()}", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<GetItemsResponse>, t: Throwable) {
                Toast.makeText(this@ShopItemsActivity, "Error: ${t.message}", Toast.LENGTH_LONG).show()
            }
        })
    }


}
