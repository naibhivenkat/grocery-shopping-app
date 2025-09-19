package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.databinding.ActivityOrderSummaryBinding
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.models.CreateOrderRequest
import com.example.groceryshoppingapp.models.OrderItemRequest
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.gson.Gson
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
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
        val apiService = RetrofitClient.getInstance(this).create(ApiService::class.java)

        val itemsList = cartItems.map { item ->
            OrderItemRequest(
                item_id = item.item.id,
                quantity = item.quantity
            )
        }

        val orderData = CreateOrderRequest(
            shopId = shopId!!,               // ✅ matches backend
            payment_method = paymentMethod,
            items = itemsList
        )

        val call = apiService.createOrder(orderData)

        call.enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(
                call: Call<Map<String, Any>>,
                response: Response<Map<String, Any>>
            ) {
                if (response.isSuccessful) {
                    Toast.makeText(this@OrderSummaryActivity, "Order Confirmed!", Toast.LENGTH_SHORT).show()
                    CartManager.clearCart(shopId)

                    val intent = Intent(this@OrderSummaryActivity, ThankYouActivity::class.java)
                    intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
                    startActivity(intent)
                    finish()
                } else {
                    Log.e("OrderSummaryActivity", "Error: ${response.code()} - ${response.errorBody()?.string()}")
                    Toast.makeText(this@OrderSummaryActivity, "Failed to confirm order!", Toast.LENGTH_LONG).show()
                }
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                Log.e("OrderSummaryActivity", "Network Error", t)
                Toast.makeText(this@OrderSummaryActivity, "Network error: ${t.message}", Toast.LENGTH_LONG).show()
            }
        })
    }



}
