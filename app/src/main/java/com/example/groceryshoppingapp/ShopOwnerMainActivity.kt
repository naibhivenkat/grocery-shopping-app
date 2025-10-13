package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.models.Order
import com.example.groceryshoppingapp.models.Shop
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ShopOwnerMainActivity : AppCompatActivity() {

    private lateinit var shopNameTv: TextView
    private lateinit var recyclerView: RecyclerView
    private lateinit var ordersAdapter: OrdersAdapter
    private val orders = mutableListOf<Order>()
    private var currentShopName: String? = null // 🏪 Store shop name

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_shop_owner_main)

        shopNameTv = findViewById(R.id.text_shop_name)
        recyclerView = findViewById(R.id.recycler_orders)
        recyclerView.layoutManager = LinearLayoutManager(this)

        val refreshBtn = findViewById<Button>(R.id.btn_refresh_orders)
        val backBtn = findViewById<Button>(R.id.btn_back)

        refreshBtn.setOnClickListener { fetchOrders() }
        backBtn.setOnClickListener { finish() }

        // Initialize adapter
        ordersAdapter = OrdersAdapter(
            orders,
            onStatusClick = { selectedOrder ->
                val intent = Intent(this, OrderDetailActivity::class.java)
                intent.putExtra("order", selectedOrder)
                startActivity(intent)
            },
            highlightCancelled = true
        )
        recyclerView.adapter = ordersAdapter

        fetchShopInfoAndOrders()
    }

    /**
     * Fetch all shops, find current shop by ID, then load orders.
     */
    private fun fetchShopInfoAndOrders() {
        val shopId = SessionManager.getShopId(this)
        if (shopId.isNullOrEmpty()) {
            Toast.makeText(this, "No shop assigned.", Toast.LENGTH_LONG).show()
            return
        }

        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.getAllShops().enqueue(object : Callback<List<Shop>> {
            override fun onResponse(call: Call<List<Shop>>, response: Response<List<Shop>>) {
                if (response.isSuccessful) {
                    val shops = response.body().orEmpty()
                    val shop = shops.find { it.id == shopId }

                    currentShopName = shop?.name ?: "My Shop"
                    shopNameTv.text = "Shop: $currentShopName"
                } else {
                    currentShopName = "My Shop"
                    shopNameTv.text = "Shop: $currentShopName"
                }
                fetchOrders()
            }

            override fun onFailure(call: Call<List<Shop>>, t: Throwable) {
                Toast.makeText(
                    this@ShopOwnerMainActivity,
                    "Failed to load shop info: ${t.message}",
                    Toast.LENGTH_SHORT
                ).show()
                currentShopName = "My Shop"
                fetchOrders()
            }
        })
    }

    private fun fetchOrders() {
        val shopId = SessionManager.getShopId(this)
        if (shopId.isNullOrEmpty()) {
            Toast.makeText(this, "No shop assigned.", Toast.LENGTH_LONG).show()
            return
        }

        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.getShopOrders(shopId).enqueue(object : Callback<List<Order>> {
            override fun onResponse(call: Call<List<Order>>, response: Response<List<Order>>) {
                if (response.isSuccessful) {
                    val list = response.body().orEmpty()

                    // Attach shop name to each order
                    val namedOrders = list.map { it.copy(shopName = currentShopName) }

                    // Sort orders by status
                    val sorted = namedOrders.sortedWith(compareBy { statusPriority(it.status) })

                    orders.clear()
                    orders.addAll(sorted)
                    ordersAdapter.notifyDataSetChanged()

                    if (list.isEmpty()) {
                        Toast.makeText(
                            this@ShopOwnerMainActivity,
                            "No orders assigned to your shop.",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                } else {
                    showToast("Failed to load: ${response.code()}")
                }
            }

            override fun onFailure(call: Call<List<Order>>, t: Throwable) {
                showToast("Error: ${t.message}")
            }
        })
    }

    private fun statusPriority(status: String): Int {
        return when (status.lowercase()) {
            "pending" -> 0
            "packed" -> 1
            "delivered" -> 2
            "cancelled" -> 3
            else -> 4
        }
    }

    private fun showToast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }
}
