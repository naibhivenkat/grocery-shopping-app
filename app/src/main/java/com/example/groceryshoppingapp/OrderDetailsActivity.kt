package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.*
import androidx.annotation.RequiresApi
import androidx.appcompat.app.AlertDialog
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
    private lateinit var btnViewInvoice: Button

    private lateinit var textPartialRefund: TextView
    private lateinit var textOrderTotal: TextView

    // 🔴 ADDED
    private lateinit var textRefundInfo: TextView

    private var selectedRefundMode: String? = null
    private lateinit var adapter: OrderItemAdapter

    private var updateItemsCall: Call<Map<String, Any>>? = null
    private var updateStatusCall: Call<Map<String, Any>>? = null
    private var refreshOrderCall: Call<Order>? = null
    private var loadShopCall: Call<Shop>? = null

    @RequiresApi(Build.VERSION_CODES.O)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_order_details)

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
        btnViewInvoice = findViewById(R.id.btn_invoice)
        textPartialRefund = findViewById(R.id.text_partial_refund)
        textOrderTotal = findViewById(R.id.text_order_total)

        // 🔴 ADDED
        textRefundInfo = findViewById(R.id.text_refund_info)

        val btnBack = findViewById<Button>(R.id.btn_back)
        order = intent.getParcelableExtra("order")!!

        setupUI()
        loadShopName()

        btnBack.setOnClickListener { finish() }
        btnRefresh.setOnClickListener { refreshOrder() }
        btnUpdateStatus.setOnClickListener { updateOrderStatus() }
        btnSaveItems.setOnClickListener { saveItemChanges() }

        btnViewInvoice.setOnClickListener {
            val intent = Intent(this, InvoiceViewActivity::class.java)
            intent.putExtra("order_id", order.orderUuid)
            startActivity(intent)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        updateItemsCall?.cancel()
        updateStatusCall?.cancel()
        refreshOrderCall?.cancel()
        loadShopCall?.cancel()
    }

    private fun calculateTotals() {
        var total = 0.0
        var refund = 0.0

        order.items.forEach {
            total += it.originalQuantity * it.price
            if (it.originalQuantity > it.quantity) {
                refund += (it.originalQuantity - it.quantity) * it.price
            }
        }

        textOrderTotal.text = "Total: ₹ %.2f".format(total)
        order.partialRefundAmount = refund
    }

    @RequiresApi(Build.VERSION_CODES.O)
    private fun setupUI() {
        updateStatusText(order.status)

        val role = SessionManager.getRole(this)
        val isShopOwner = role == "shopowner" || role == "shopkeeper"

        adapter = OrderItemAdapter(order.items.toMutableList(), isShopOwner)
        recyclerItems.layoutManager = LinearLayoutManager(this)
        recyclerItems.adapter = adapter

        calculateTotals()

        textCreatedAt.text = "Created At: ${order.createdAt?.let { formatToIST(it) }}"

        order.transaction_id?.let {
            textPayment.text =
                "Payment: ${order.payment_method ?: "UPI"} (TxnRef: $it)"
            textPayment.visibility = View.VISIBLE
        } ?: run { textPayment.visibility = View.GONE }

        if (!isShopOwner && order.status.equals("delivered", true)) {
            btnViewInvoice.visibility = View.VISIBLE
        } else {
            btnViewInvoice.visibility = View.GONE
        }

        showPartialRefundUI()

        // 🔴 ADDED
//        showRefundInfoIfNeeded(isShopOwner)

        if (isShopOwner) {
            spinnerStatus.visibility = View.VISIBLE
            btnUpdateStatus.visibility = View.VISIBLE
            btnSaveItems.visibility = View.VISIBLE

            val options = listOf("Pending", "Packed", "Delivered", "Cancelled")
            spinnerStatus.adapter =
                ArrayAdapter(this, android.R.layout.simple_spinner_item, options)

            spinnerStatus.onItemSelectedListener =
                object : AdapterView.OnItemSelectedListener {
                    override fun onItemSelected(
                        parent: AdapterView<*>,
                        view: View?,
                        pos: Int,
                        id: Long
                    ) {
                        editCancelMsg.visibility =
                            if (options[pos] == "Cancelled") View.VISIBLE else View.GONE
                    }

                    override fun onNothingSelected(parent: AdapterView<*>) {}
                }
        } else {
            spinnerStatus.visibility = View.GONE
            btnUpdateStatus.visibility = View.GONE
            btnSaveItems.visibility = View.GONE
        }
    }


    private fun updateOrderStatus() {
        val selectedStatus = spinnerStatus.selectedItem.toString()
        if (selectedStatus.equals("Cancelled", true)) {
            showRefundModeDialog { sendStatusUpdate(selectedStatus) }
            return
        }
        sendStatusUpdate(selectedStatus)
    }

    private fun showRefundModeDialog(onConfirm: () -> Unit) {
        val options = arrayOf("Razorpay", "Shop Wallet", "Cash Paid")
        AlertDialog.Builder(this)
            .setTitle("Refund Method")
            .setSingleChoiceItems(options, -1) { _, which ->
                selectedRefundMode = when (which) {
                    0 -> "RAZORPAY"
                    1 -> "SHOP_WALLET"
                    else -> "CASH"
                }
            }
            .setPositiveButton("Confirm") { _, _ ->
                if (selectedRefundMode != null) onConfirm()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun sendStatusUpdate(status: String) {
        val body = mutableMapOf(
            "order_id" to order.orderUuid,
            "status" to status
        )
        selectedRefundMode?.let { body["refund_mode"] = it }

        updateStatusCall = RetrofitClient.getInstance(this)
            .create(ApiService::class.java)
            .updateOrderStatusFinal(body)

        updateStatusCall?.enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(
                call: Call<Map<String, Any>>,
                response: Response<Map<String, Any>>
            ) {
                refreshOrder()
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {}
        })
    }

    private fun saveItemChanges() {
        if (order.partialRefundAmount != null && order.partialRefundAmount!! > 0) {
            showRefundModeDialog { proceedSaveItems() }
            return
        }
        proceedSaveItems()
    }

    private fun proceedSaveItems() {
        val updatedItems = adapter.getUpdatedItems()
        val itemsPayload = updatedItems.map {
            com.example.groceryshoppingapp.network.OrderItemPayload(
                item_id = it.itemId,
                quantity = it.quantity,
                price = it.price,
                comment = it.comment ?: ""
            )
        }

        val payload =
            com.example.groceryshoppingapp.network.UpdateOrderItemsRequest(itemsPayload)

        updateItemsCall =
            RetrofitClient.getInstance(this)
                .create(ApiService::class.java)
                .updateOrderItems(order.orderUuid, payload)

        updateItemsCall?.enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(
                call: Call<Map<String, Any>>,
                response: Response<Map<String, Any>>
            ) {
                refreshOrder()
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {}
        })
    }

    private fun showPartialRefundUI() {
        val refund = order.partialRefundAmount
        if (refund != null && refund > 0) {
            textPartialRefund.text = "Partial Refund: ₹ %.2f".format(refund)
            textPartialRefund.visibility = View.VISIBLE
        } else {
            textPartialRefund.visibility = View.GONE
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


    private fun loadShopName() {
        if (!order.shopName.isNullOrEmpty()) {
            textShopName.text = "Shop: ${order.shopName}"
            return
        }

        order.shopId?.let {
            loadShopCall =
                RetrofitClient.getInstance(this)
                    .create(ApiService::class.java)
                    .getShop(it)

            loadShopCall?.enqueue(object : Callback<Shop> {
                override fun onResponse(call: Call<Shop>, response: Response<Shop>) {
                    textShopName.text =
                        "Shop: ${response.body()?.name ?: "Unknown"}"
                }

                override fun onFailure(call: Call<Shop>, t: Throwable) {
                    textShopName.text = "Shop: Unknown"
                }
            })
        }
    }

    private fun refreshOrder() {
        refreshOrderCall =
            RetrofitClient.getInstance(this)
                .create(ApiService::class.java)
                .getOrderById(order.orderUuid)

        refreshOrderCall?.enqueue(object : Callback<Order> {
            override fun onResponse(call: Call<Order>, response: Response<Order>) {
                order = response.body() ?: return
                setupUI()
            }

            override fun onFailure(call: Call<Order>, t: Throwable) {}
        })
    }

    @RequiresApi(Build.VERSION_CODES.O)
    private fun formatToIST(utcTime: String): String {
        return ZonedDateTime.parse(utcTime)
            .withZoneSameInstant(ZoneId.of("Asia/Kolkata"))
            .format(DateTimeFormatter.ofPattern("dd MMM yyyy, hh:mm a"))
    }
}
