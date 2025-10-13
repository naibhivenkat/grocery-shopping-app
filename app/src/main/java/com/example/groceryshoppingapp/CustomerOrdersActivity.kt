package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.*
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

class CustomerOrdersActivity : AppCompatActivity() {

    private lateinit var ordersRecyclerView: RecyclerView
    private lateinit var emptyTextView: TextView
    private val allOrdersList = mutableListOf<Order>()
    private val filteredOrdersList = mutableListOf<Order>()
    private lateinit var ordersAdapter: OrdersAdapter

    private lateinit var spinnerFilter: Spinner
    private lateinit var refreshBtn: Button
    private lateinit var backBtn: Button

    // ✅ Keep shopMap globally
    private var shopMap: Map<String, String> = emptyMap()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_customer_orders)

        ordersRecyclerView = findViewById(R.id.recycler_orders)
        emptyTextView = findViewById(R.id.text_orders)
        spinnerFilter = findViewById(R.id.spinner_filter)
        refreshBtn = findViewById(R.id.btn_refresh_orders)
        backBtn = findViewById(R.id.btn_back)

        ordersRecyclerView.layoutManager = LinearLayoutManager(this)

        ordersAdapter = OrdersAdapter(
            filteredOrdersList,
            shopMap = emptyMap(),
            onStatusClick = { selectedOrder ->
                val intent = Intent(this, OrderDetailActivity::class.java)
                intent.putExtra("order", selectedOrder)
                startActivity(intent)
            }
        )
        ordersRecyclerView.adapter = ordersAdapter

        setupFilterSpinner()

        refreshBtn.setOnClickListener { fetchOrders() }
        backBtn.setOnClickListener { finish() }

        // ✅ Fetch shops first, then orders
        fetchShopsAndOrders()
    }

    private fun setupFilterSpinner() {
        val filterOptions = listOf("All", "Pending", "Packed", "Completed", "Cancelled")
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, filterOptions)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        spinnerFilter.adapter = adapter

        spinnerFilter.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val selectedStatus = filterOptions[position].lowercase()
                filterOrders(selectedStatus)
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
    }

    // ✅ New helper to fetch shops first
    private fun fetchShopsAndOrders() {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.getAllShops().enqueue(object : Callback<List<Shop>> {
            override fun onResponse(call: Call<List<Shop>>, response: Response<List<Shop>>) {
                if (response.isSuccessful) {
                    val shops = response.body() ?: emptyList()
                    shopMap = shops.associate { it.id to it.name }  // ✅ build shopId → shopName map
                }
                fetchOrders() // ✅ fetch orders after we have shop names
            }

            override fun onFailure(call: Call<List<Shop>>, t: Throwable) {
                Log.e("CustomerOrders", "Failed to fetch shops: ${t.message}")
                fetchOrders() // ✅ still fetch orders even if shops fail
            }
        })
    }

    private fun fetchOrders() {
        val customerId = SessionManager.getCustomerId(this)
        if (customerId.isNullOrEmpty()) {
            Toast.makeText(this, "Invalid session. Please login again.", Toast.LENGTH_SHORT).show()
            return
        }

        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.getCustomerOrders(customerId).enqueue(object : retrofit2.Callback<List<Order>> {
            override fun onResponse(
                call: retrofit2.Call<List<Order>>,
                response: retrofit2.Response<List<Order>>
            ) {
                if (response.isSuccessful) {
                    val orders = response.body() ?: emptyList()
                    allOrdersList.clear()
                    allOrdersList.addAll(orders)

                    // ✅ Update adapter with proper shop map
                    ordersAdapter = OrdersAdapter(
                        filteredOrdersList,
                        shopMap = shopMap,
                        onStatusClick = { selectedOrder ->
                            val intent = Intent(this@CustomerOrdersActivity, OrderDetailActivity::class.java)
                            intent.putExtra("order", selectedOrder)
                            startActivity(intent)
                        }
                    )
                    ordersRecyclerView.adapter = ordersAdapter

                    filterOrders("all")
                    spinnerFilter.setSelection(0)
                } else {
                    Toast.makeText(this@CustomerOrdersActivity, "Failed to load orders", Toast.LENGTH_SHORT).show()
                    Log.e("CustomerOrders", "Error: ${response.errorBody()?.string()}")
                }
            }

            override fun onFailure(call: retrofit2.Call<List<Order>>, t: Throwable) {
                Toast.makeText(this@CustomerOrdersActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
                Log.e("CustomerOrders", "Network error", t)
            }
        })
    }

    private fun filterOrders(status: String) {
        filteredOrdersList.clear()
        filteredOrdersList.addAll(
            when (status) {
                "all" -> allOrdersList
                "pending" -> allOrdersList.filter { it.status.equals("Pending", true) }
                "packed" -> allOrdersList.filter { it.status.equals("Packed", true) }
                "completed" -> allOrdersList.filter { it.status.equals("Delivered", true) }
                "cancelled" -> allOrdersList.filter { it.status.equals("Cancelled", true) }
                else -> allOrdersList
            }
        )

        ordersAdapter.notifyDataSetChanged()

        emptyTextView.visibility = if (filteredOrdersList.isEmpty()) View.VISIBLE else View.GONE
        ordersRecyclerView.visibility = if (filteredOrdersList.isEmpty()) View.GONE else View.VISIBLE
    }
}
