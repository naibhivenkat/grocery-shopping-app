package com.example.groceryshoppingapp

import android.os.Bundle
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.OrderItemAdapter
import com.example.groceryshoppingapp.models.Order
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class OrderDetailActivity : AppCompatActivity() {

    private lateinit var order: Order
    private lateinit var textStatus: TextView
    private lateinit var spinnerStatus: Spinner
    private lateinit var editCancelMsg: EditText
    private lateinit var btnUpdateStatus: Button
    private lateinit var btnRefresh: Button
    private lateinit var recyclerItems: RecyclerView
    private lateinit var textShopName: TextView
    private lateinit var textCreatedAt: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_order_details)

        // Init views
        textShopName = findViewById(R.id.text_shop_name)
        textStatus = findViewById(R.id.text_status)
        textCreatedAt = findViewById(R.id.text_created_at)
        recyclerItems = findViewById(R.id.recycler_items)

        spinnerStatus = findViewById(R.id.spinner_status)
        editCancelMsg = findViewById(R.id.edit_cancel_msg)
        btnUpdateStatus = findViewById(R.id.btn_update_status)
        btnRefresh = findViewById(R.id.btn_refresh)
        val btnBack = findViewById<Button>(R.id.btn_back)

        // Get order from intent
        order = intent.getParcelableExtra("order")!!

        setupUI()

        // Back button
        btnBack.setOnClickListener {
            finish()
        }

        // Refresh button
        btnRefresh.setOnClickListener {
            refreshOrder()
        }

        // Update button
        btnUpdateStatus.setOnClickListener {
            val selectedStatus = spinnerStatus.selectedItem.toString()
            val cancelMsg = editCancelMsg.text.toString()

            val updateMap = mutableMapOf<String, String>()
            updateMap["status"] = selectedStatus.lowercase()
            if (selectedStatus == "Cancelled" && cancelMsg.isNotBlank()) {
                updateMap["cancel_message"] = cancelMsg
            }

            RetrofitClient.getInstance(this).create(ApiService::class.java)
                .updateOrder(order.orderUuid, updateMap)
                .enqueue(object : Callback<Map<String, Any>> {
                    override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                        Toast.makeText(this@OrderDetailActivity, "Order updated!", Toast.LENGTH_SHORT).show()
                        refreshOrder()
                    }

                    override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                        Toast.makeText(this@OrderDetailActivity, "Failed to update", Toast.LENGTH_SHORT).show()
                    }
                })
        }
    }

    private fun setupUI() {
        textShopName.text = "Shop: ${order.shopName}"
        textStatus.text = "Status: ${order.status}"
        textCreatedAt.text = "Created At: ${order.createdAt}"

        recyclerItems.layoutManager = LinearLayoutManager(this)
        recyclerItems.adapter = OrderItemAdapter(order.items)

        val role = SessionManager.getRole(this)

        if (role == "shopowner") {
            spinnerStatus.visibility = View.VISIBLE
            btnUpdateStatus.visibility = View.VISIBLE

            val options = listOf("Pending", "Packed", "Delivered", "Cancelled")
            val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, options)
            adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            spinnerStatus.adapter = adapter

            //val currentIndex = options.indexOf(order.status)
            val currentIndex = options.indexOfFirst { it.equals(order.status, ignoreCase = true) }

            if (currentIndex >= 0) spinnerStatus.setSelection(currentIndex)

            spinnerStatus.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(parent: AdapterView<*>, view: View?, pos: Int, id: Long) {
                    editCancelMsg.visibility = if (options[pos] == "Cancelled") View.VISIBLE else View.GONE
                }

                override fun onNothingSelected(parent: AdapterView<*>) {}
            }
        } else {
            spinnerStatus.visibility = View.GONE
            btnUpdateStatus.visibility = View.GONE
            editCancelMsg.visibility = View.GONE
        }
    }

    private fun refreshOrder() {
        RetrofitClient.getInstance(this).create(ApiService::class.java)
            .getOrderById(order.orderUuid)
            .enqueue(object : Callback<Order> {
                override fun onResponse(call: Call<Order>, response: Response<Order>) {
                    if (response.isSuccessful) {
                        order = response.body()!!
                        textStatus.text = "Status: ${order.status}"
                        recyclerItems.adapter = OrderItemAdapter(order.items)

                        val options = listOf("Pending", "Packed", "Delivered", "Cancelled")
                        val index = options.indexOfFirst { it.equals(order.status, ignoreCase = true) }

                       // val index = options.indexOf(order.status)
                        if (index >= 0) spinnerStatus.setSelection(index)
                    } else {
                        Toast.makeText(this@OrderDetailActivity, "Failed to refresh order", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<Order>, t: Throwable) {
                    Toast.makeText(this@OrderDetailActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }

}
