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
import com.example.groceryshoppingapp.models.Order
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
    // private val ordersList = mutableListOf<Order>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_shop_owner_main)

        shopNameTv = findViewById(R.id.text_shop_name)
        recyclerView = findViewById(R.id.recycler_orders)
        recyclerView.layoutManager = LinearLayoutManager(this)


        val refreshBtn = findViewById<Button>(R.id.btn_refresh_orders)
        val backBtn = findViewById<Button>(R.id.btn_back)

        refreshBtn.setOnClickListener {
            fetchOrders()
        }

        backBtn.setOnClickListener {
            finish()
        }

        ordersAdapter = OrdersAdapter(
            orders,
            onStatusClick = { selectedOrder ->
                val intent = Intent(this, OrderDetailActivity::class.java)
                intent.putExtra("order", selectedOrder)
                startActivity(intent)
            }
        )

        recyclerView.adapter = ordersAdapter

        displayShopInfo()
        fetchOrders()
    }
    private fun displayShopInfo() {
        val shopName = SessionManager.getShopName(this)
        shopNameTv.text = shopName?.let { "Shop: $it" } ?: "My Shop"
    }

    private fun fetchOrders() {
        val shopId = SessionManager.getShopId(this)
        if (shopId.isNullOrEmpty()) {
            Toast.makeText(this, "No shop assigned.", Toast.LENGTH_LONG).show()
            return
        }

        RetrofitClient.getInstance(this).create(ApiService::class.java)
            .getShopOrders(shopId)
            .enqueue(object : Callback<List<Order>> {
                override fun onResponse(call: Call<List<Order>>, response: Response<List<Order>>) {
                    if (response.isSuccessful) {
                        val list = response.body().orEmpty()
                        if (list.isEmpty()) {
                            Toast.makeText(this@ShopOwnerMainActivity, "No orders assigned to your shop.", Toast.LENGTH_SHORT).show()
                        }
                        orders.clear()
                        orders.addAll(list)
                        ordersAdapter.notifyDataSetChanged()
                    } else {
                        showToast("Failed to load: ${response.code()}")
                    }
                }

                override fun onFailure(call: Call<List<Order>>, t: Throwable) {
                    showToast("Error: ${t.message}")
                }
            })
    }


    private fun showToast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }
}
