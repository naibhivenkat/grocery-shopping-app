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
        val customerName = SessionManager.getUsername(this) ?: ""
        val url = "https://grocery-shopping-app-yyqx.onrender.com/api/orders/customer/$customerName"

        val request = JsonArrayRequest(
            Request.Method.GET, url, null,
            { response: JSONArray ->
                if (response.length() == 0) {
                    emptyTextView.visibility = View.VISIBLE
                    ordersRecyclerView.visibility = View.GONE
                } else {
                    allOrdersList.clear()
                    filteredOrdersList.clear()

                    for (i in 0 until response.length()) {
                        val orderObj = response.getJSONObject(i)
                        val orderUuid = orderObj.getString("order_uuid")
                        val customer = orderObj.getString("customer")
                        val status = orderObj.getString("status")
                        val createdAt = orderObj.optString("created_at", "Unknown")
                        val shopName = orderObj.optString("shop_name", "Unknown Shop")

                        val itemsArray = orderObj.getJSONArray("items")
                        val itemQuantities = mutableListOf<ItemQuantity>()
                        for (j in 0 until itemsArray.length()) {
                            val itemObj = itemsArray.getJSONObject(j)
                            val itemJson = itemObj.getJSONObject("item")

                            val item = Item(
                                id = itemJson.getString("id"),
                                name = itemJson.getString("name"),
                                price = itemJson.getDouble("price"),
                                stockQuantity = itemJson.getInt("stock_quantity"),
                                description = itemJson.getString("description"),
                                shopid = itemJson.getString("shopid")
                            )
                            val quantity = itemObj.getInt("quantity")
                            itemQuantities.add(ItemQuantity(item, quantity))
                        }

                        val order = Order(
                            orderUuid = orderUuid,
                            customerName = customer,
                            items = itemQuantities,
                            status = status,
                            createdAt = createdAt,
                            shopName = shopName
                        )

                        allOrdersList.add(order)
                    }

                    spinnerFilter.setSelection(0) // Default to "ALL ORDERS"
                }
            },
            { error ->
                Log.e("OrdersFetchError", "Volley error: $error")
                Toast.makeText(this, "Failed to fetch orders", Toast.LENGTH_SHORT).show()
            }
        )

        Volley.newRequestQueue(this).add(request)
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
