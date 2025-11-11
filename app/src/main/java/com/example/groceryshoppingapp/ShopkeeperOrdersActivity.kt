package com.example.groceryshoppingapp

import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.databinding.ActivityShopkeeperOrdersBinding
import com.example.groceryshoppingapp.models.Order
import com.example.groceryshoppingapp.network.ApiResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ShopkeeperOrdersActivity : AppCompatActivity() {

    private lateinit var binding: ActivityShopkeeperOrdersBinding
    private lateinit var orderAdapter: ShopOrderAdapter
    private var shopkeeperId: String? = null
    private var orders: List<Order> = listOf()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityShopkeeperOrdersBinding.inflate(layoutInflater)
        setContentView(binding.root)

        shopkeeperId = intent.getStringExtra("shopkeeper_id")
            ?: SessionManager.getShopkeeperId(this)

        if (shopkeeperId.isNullOrEmpty()) {
            Toast.makeText(this, "Invalid shopkeeper ID", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        orderAdapter = ShopOrderAdapter(orders) { orderId, status ->
            updateOrderStatus(orderId, status)
        }



        binding.ordersRecyclerView.layoutManager = LinearLayoutManager(this)
        binding.ordersRecyclerView.adapter = orderAdapter

        // 1️⃣ Show cached orders instantly
        orders = SessionManager.getCachedShopOrders(this)
        orderAdapter.updateOrders(orders)
        binding.tvEmptyOrders.visibility = if (orders.isEmpty()) View.VISIBLE else View.GONE

        // 2️⃣ Listen for background updates from preload
        SessionManager.setShopOrdersListener { updatedOrders ->
            runOnUiThread {
                orders = updatedOrders
                orderAdapter.updateOrders(orders)
                binding.tvEmptyOrders.visibility = if (orders.isEmpty()) View.VISIBLE else View.GONE
            }
        }

        // 3️⃣ Optional: fetch immediately if cache empty (first login)
        if (orders.isEmpty()) fetchOrders()
    }

    override fun onResume() {
        super.onResume()
        // Refresh UI from cache (in case something changed while paused)
        val cachedOrders = SessionManager.getCachedShopOrders(this)
        if (cachedOrders != orders) {
            orders = cachedOrders
            orderAdapter.updateOrders(orders)
            binding.tvEmptyOrders.visibility = if (orders.isEmpty()) View.VISIBLE else View.GONE
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        SessionManager.clearShopOrdersListener()
    }

    private fun fetchOrders() {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.getShopOrders(shopkeeperId!!).enqueue(object : Callback<List<Order>> {
            override fun onResponse(call: Call<List<Order>>, response: Response<List<Order>>) {
                if (response.isSuccessful && response.body() != null) {
                    orders = response.body()!!
                    SessionManager.cacheShopOrders(this@ShopkeeperOrdersActivity, orders)
                } else {
                    Toast.makeText(this@ShopkeeperOrdersActivity, "Failed to load orders", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<List<Order>>, t: Throwable) {
                Toast.makeText(this@ShopkeeperOrdersActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

//    private fun updateOrderStatus(orderId: String, status: String) {
//        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
//        api.updateOrderStatus(orderId, status).enqueue(object : Callback<ApiResponse> {
//            override fun onResponse(call: Call<ApiResponse>, response: Response<ApiResponse>) {
//                if (response.isSuccessful && response.body()?.success == true) {
//                    Toast.makeText(this@ShopkeeperOrdersActivity, "Order updated", Toast.LENGTH_SHORT).show()
//                    // Update cache/UI after successful update
//                    fetchOrders()
//                } else {
//                    Toast.makeText(this@ShopkeeperOrdersActivity, "Failed to update order", Toast.LENGTH_SHORT).show()
//                }
//            }
//
//            override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
//                Toast.makeText(this@ShopkeeperOrdersActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
//            }
//        })
//    }

    private fun updateOrderStatus(orderId: String, status: String) {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.updateOrderStatus(orderId, status).enqueue(object : Callback<ApiResponse> {
            override fun onResponse(call: Call<ApiResponse>, response: Response<ApiResponse>) {
                if (response.isSuccessful && response.body()?.success == true) {
                    val invoiceUrl = response.body()?.invoiceUrl
                    if (!invoiceUrl.isNullOrEmpty()) {
                        Toast.makeText(this@ShopkeeperOrdersActivity, "Invoice created: $invoiceUrl", Toast.LENGTH_LONG).show()
                    } else {
                        Toast.makeText(this@ShopkeeperOrdersActivity, "Order updated: $status", Toast.LENGTH_SHORT).show()
                    }
                    fetchOrders()
                } else {
                    Toast.makeText(this@ShopkeeperOrdersActivity, "Failed to update order", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
                Toast.makeText(this@ShopkeeperOrdersActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }





}
