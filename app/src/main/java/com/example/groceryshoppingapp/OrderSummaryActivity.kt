package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.android.volley.toolbox.JsonObjectRequest
import com.android.volley.toolbox.Volley
import com.example.groceryshoppingapp.databinding.ActivityOrderSummaryBinding
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.*

class OrderSummaryActivity : AppCompatActivity() {

    private lateinit var binding: ActivityOrderSummaryBinding
    private var cartItems: List<CartItem> = emptyList()
    private var totalAmount: Double = 0.0
    private var paymentMethod: String = "Unknown"
    private var shopName: String = "My Grocery Shop"

    private var customerId: String? = null
    private var shopId: String? = null
    private var userName : String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOrderSummaryBinding.inflate(layoutInflater)
        setContentView(binding.root)

        try {
            cartItems = intent.getParcelableArrayListExtra<CartItem>("cart") ?: emptyList()
        } catch (e: Exception) {
            Log.e("OrderSummaryActivity", "Error retrieving cartItems", e)
            cartItems = emptyList()
        }

        totalAmount = intent.getDoubleExtra("total", 0.0)
        paymentMethod = intent.getStringExtra("payment") ?: "Unknown"

        customerId = SessionManager.getCustomerId(this)

        shopId = SessionManager.getShopId(this)
        shopName = SessionManager.getShopName(this) ?: "My Grocery Shop"

        if (customerId.isNullOrEmpty() || shopId.isNullOrEmpty()) {
            Toast.makeText(this, "Session expired or invalid. Please log in again.", Toast.LENGTH_LONG).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val formattedTime = SimpleDateFormat("dd MMM yyyy, hh:mm a", Locale.getDefault()).format(Date())

        binding.textViewShopName.text = "Shop: $shopName"
        binding.textViewPayment.text = "Payment: $paymentMethod"
        binding.textViewOrderTime.text = "Time: $formattedTime"
        binding.textViewTotal.text = "Total: ₹%.2f".format(totalAmount)

        val itemsText = if (cartItems.isNotEmpty()) {
            cartItems.joinToString("\n") {
                "${it.item.name} - ₹${it.item.price} x ${it.quantity} = ₹%.2f".format(it.item.price * it.quantity)
            }
        } else {
            "No items in the cart."
        }
        binding.orderItems.text = itemsText

        binding.buttonCancel.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Cancel Order")
                .setMessage("Are you sure you want to cancel the order?")
                .setPositiveButton("Yes") { _, _ ->
                    Toast.makeText(this, "Order Cancelled", Toast.LENGTH_SHORT).show()
                    finish()
                }
                .setNegativeButton("No", null)
                .show()
        }

        binding.buttonModify.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Modify Order")
                .setMessage("Do you want to go back and modify the order?")
                .setPositiveButton("Yes") { _, _ ->
                    val intent = Intent(this, OrderConfirmActivity::class.java)
                    intent.putParcelableArrayListExtra("cart", ArrayList(cartItems))
                    intent.putExtra("total", totalAmount)
                    intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP
                    startActivity(intent)
                    finish()
                }
                .setNegativeButton("No", null)
                .show()
        }

        binding.buttonConfirmFinal.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Confirm Order")
                .setMessage("Are you sure you want to finalize the order?")
                .setPositiveButton("Confirm") { _, _ ->
                    sendOrderToBackend()
                }
                .setNegativeButton("Cancel", null)
                .show()
        }
    }

    private fun sendOrderToBackend() {
        val url = "https://grocery-shopping-app-yyqx.onrender.com/api/orders"
        val userName =  SessionManager.getUsername(this)

        val orderJson = JSONObject().apply {
            put("customer", userName)
            put("shop_id", shopId)
            put("payment_method", paymentMethod)

            val itemsArray = JSONArray()
            for (item in cartItems) {
                val itemObj = JSONObject().apply {
                    put("item_id", item.item.id)
                    put("quantity", item.quantity)
                }
                itemsArray.put(itemObj)
            }
            put("items", itemsArray)
        }

        val request = object : JsonObjectRequest(
            Method.POST, url, orderJson,
            { response ->
                Toast.makeText(this@OrderSummaryActivity, "Order Confirmed!", Toast.LENGTH_SHORT).show()
                CartManager.clearCart(shopId)

                val intent = Intent(this@OrderSummaryActivity, ThankYouActivity::class.java)
                intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
                startActivity(intent)
                finish()
            },
            { error ->
                Log.e("OrderSummaryActivity", "Failed to send order", error)
                Toast.makeText(this@OrderSummaryActivity, "Failed to confirm order!", Toast.LENGTH_LONG).show()
            }
        ) {
            override fun getHeaders(): MutableMap<String, String> {
                val headers = HashMap<String, String>()
                headers["Content-Type"] = "application/json"
                return headers
            }
        }

        Volley.newRequestQueue(this).add(request)
    }
}
