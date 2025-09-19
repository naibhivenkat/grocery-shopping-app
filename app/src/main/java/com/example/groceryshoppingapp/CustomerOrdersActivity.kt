package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.android.volley.Request
import com.android.volley.toolbox.JsonArrayRequest
import com.android.volley.toolbox.Volley
import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.models.ItemQuantity
import com.example.groceryshoppingapp.models.Order
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import org.json.JSONArray

class CustomerOrdersActivity : AppCompatActivity() {

    private lateinit var ordersRecyclerView: RecyclerView
    private lateinit var emptyTextView: TextView
    private val allOrdersList = mutableListOf<Order>()
    private val filteredOrdersList = mutableListOf<Order>()
    private lateinit var ordersAdapter: OrdersAdapter

    private lateinit var spinnerFilter: Spinner
    private lateinit var refreshBtn: Button
    private lateinit var backBtn: Button

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

        fetchOrders()
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



    private fun fetchOrders() {
        val customerId = SessionManager.getCustomerId(this)
        if (customerId.isNullOrEmpty()) {
            Toast.makeText(this, "Invalid session. Please login again.", Toast.LENGTH_SHORT).show()
            return
        }

        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        val call = api.getCustomerOrders(customerId)
        call.enqueue(object : retrofit2.Callback<List<Order>> {
            override fun onResponse(
                call: retrofit2.Call<List<Order>>,
                response: retrofit2.Response<List<Order>>
            ) {
                if (response.isSuccessful) {
                    val orders = response.body() ?: emptyList()
                    allOrdersList.clear()
                    allOrdersList.addAll(orders)
                    spinnerFilter.setSelection(0) // default to "All"
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
                "pending" -> allOrdersList.filter { it.status.equals("pending", true) }
                "packed" -> allOrdersList.filter { it.status.equals("packed", true) }
                "completed" -> allOrdersList.filter { it.status.equals("delivered", true) }
                "cancelled" -> allOrdersList.filter { it.status.equals("cancelled", true) }
                else -> allOrdersList
            }
        )
        ordersAdapter.notifyDataSetChanged()

        emptyTextView.visibility = if (filteredOrdersList.isEmpty()) View.VISIBLE else View.GONE
        ordersRecyclerView.visibility = if (filteredOrdersList.isEmpty()) View.GONE else View.VISIBLE
    }
}
