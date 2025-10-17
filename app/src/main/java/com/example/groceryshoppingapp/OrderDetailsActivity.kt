package com.example.groceryshoppingapp

import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.*
import androidx.annotation.RequiresApi
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.OrderItemAdapter
import com.example.groceryshoppingapp.models.ItemQuantity
import com.example.groceryshoppingapp.models.Order
import com.example.groceryshoppingapp.models.Shop
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

class OrderDetailActivity : AppCompatActivity() {

    private lateinit var order: Order
    private lateinit var textStatus: TextView
    private lateinit var textPayment: TextView
    private lateinit var spinnerStatus: Spinner
    private lateinit var editCancelMsg: EditText
    private lateinit var btnUpdateStatus: Button
    private lateinit var btnRefresh: Button
    private lateinit var btnSaveItems: Button
    private lateinit var recyclerItems: RecyclerView
    private lateinit var textShopName: TextView
    private lateinit var textCreatedAt: TextView

    private lateinit var adapter: OrderItemAdapter

    @RequiresApi(Build.VERSION_CODES.O)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_order_details)

        // Init views
        textShopName = findViewById(R.id.text_shop_name)
        textStatus = findViewById(R.id.text_status)
        textCreatedAt = findViewById(R.id.text_created_at)
        recyclerItems = findViewById(R.id.recycler_items)
        textPayment = findViewById(R.id.text_payment_info)
        spinnerStatus = findViewById(R.id.spinner_status)
        editCancelMsg = findViewById(R.id.edit_cancel_msg)
        btnUpdateStatus = findViewById(R.id.btn_update_status)
        btnRefresh = findViewById(R.id.btn_refresh)
        btnSaveItems = findViewById(R.id.btn_save_items)
        val btnBack = findViewById<Button>(R.id.btn_back)

        // Get order
        order = intent.getParcelableExtra("order")!!

        setupUI()
        loadShopName()

        btnBack.setOnClickListener { finish() }
        btnRefresh.setOnClickListener { refreshOrder() }
        btnUpdateStatus.setOnClickListener { updateOrderStatus() }

        btnSaveItems.setOnClickListener { saveItemChanges() }
    }

    @RequiresApi(Build.VERSION_CODES.O)
    private fun setupUI() {
        updateStatusText(order.status)

        val isShopOwner = SessionManager.getRole(this) == "shopowner"
        adapter = OrderItemAdapter(order.items.toMutableList(), isShopOwner)
        recyclerItems.layoutManager = LinearLayoutManager(this)
        recyclerItems.adapter = adapter

        textCreatedAt.text = "Created At: ${order.createdAt?.let { formatToIST(it) }}"
        order.transaction_id?.let {
            textPayment.text = "Payment: ${order.payment_method ?: "UPI"} (TxnRef: $it)"
            textPayment.visibility = View.VISIBLE
        } ?: run { textPayment.visibility = View.GONE }

        if (isShopOwner) {
            spinnerStatus.visibility = View.VISIBLE
            btnUpdateStatus.visibility = View.VISIBLE
            btnSaveItems.visibility = View.VISIBLE

            val options = listOf("Pending", "Packed", "Delivered", "Cancelled")
            val spinnerAdapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, options)
            spinnerAdapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            spinnerStatus.adapter = spinnerAdapter

            val currentIndex = options.indexOfFirst { it.equals(order.status, ignoreCase = true) }
            if (currentIndex >= 0) spinnerStatus.setSelection(currentIndex)

            spinnerStatus.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(parent: AdapterView<*>, view: View?, pos: Int, id: Long) {
                    editCancelMsg.visibility = if (options[pos] == "Cancelled") View.VISIBLE else View.GONE
                }
                override fun onNothingSelected(parent: AdapterView<*>) {}
            }
        }
    }

    private fun updateStatusText(status: String) {
        textStatus.text = "Status: $status"
        val colorRes = when (status.lowercase()) {
            "pending" -> android.R.color.holo_orange_dark
            "packed" -> android.R.color.holo_blue_dark
            "delivered" -> android.R.color.holo_green_dark
            "cancelled" -> android.R.color.holo_red_dark
            else -> android.R.color.black
        }
        textStatus.setTextColor(resources.getColor(colorRes))
    }

    @RequiresApi(Build.VERSION_CODES.O)
    private fun formatToIST(utcTime: String): String {
        return try {
            val zdt = ZonedDateTime.parse(utcTime)
            val istZdt = zdt.withZoneSameInstant(ZoneId.of("Asia/Kolkata"))
            istZdt.format(DateTimeFormatter.ofPattern("dd MMM yyyy, hh:mm a"))
        } catch (e: Exception) {
            utcTime
        }
    }

    private fun loadShopName() {
        if (!order.shopName.isNullOrEmpty()) {
            textShopName.text = "Shop: ${order.shopName}"
            return
        }

        order.shopId?.let {
            RetrofitClient.getInstance(this).create(ApiService::class.java)
                .getShop(it)
                .enqueue(object : Callback<Shop> {
                    override fun onResponse(call: Call<Shop>, response: Response<Shop>) {
                        val shop = response.body()
                        textShopName.text = "Shop: ${shop?.name ?: "Unknown"}"
                    }

                    override fun onFailure(call: Call<Shop>, t: Throwable) {
                        textShopName.text = "Shop: Unknown"
                    }
                })
        }
    }

    private fun refreshOrder() {
        RetrofitClient.getInstance(this).create(ApiService::class.java)
            .getOrderById(order.orderUuid)
            .enqueue(object : Callback<Order> {
                override fun onResponse(call: Call<Order>, response: Response<Order>) {
                    if (response.isSuccessful) {
                        order = response.body()!!
                        setupUI()
                        Toast.makeText(this@OrderDetailActivity, "Order refreshed", Toast.LENGTH_SHORT).show()
                    } else {
                        Toast.makeText(this@OrderDetailActivity, "Failed to refresh order", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<Order>, t: Throwable) {
                    Toast.makeText(this@OrderDetailActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }

    private fun updateOrderStatus() {
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

    private fun saveItemChanges() {
        val updatedItems: List<ItemQuantity> = adapter.getUpdatedItems()

        val payload = mapOf("items" to updatedItems.map {
            mapOf(
                "item_id" to it.itemId,
                "quantity" to it.quantity,
                "price" to it.price,
                "comment" to (it.comment ?: "")
            )
        })

        RetrofitClient.getInstance(this).create(ApiService::class.java)
            .updateOrderItems(order.orderUuid, payload)
            .enqueue(object : Callback<Map<String, Any>> {
                override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                    Toast.makeText(this@OrderDetailActivity, "Items updated successfully!", Toast.LENGTH_SHORT).show()
                }
                override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                    Toast.makeText(this@OrderDetailActivity, "Failed to save changes", Toast.LENGTH_SHORT).show()
                }
            })
    }
}
