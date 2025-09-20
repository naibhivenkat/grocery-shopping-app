package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.databinding.ActivityOrderConfirmBinding
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.models.CreateOrderRequest
import com.example.groceryshoppingapp.models.OrderItemRequest
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class OrderConfirmActivity : AppCompatActivity() {

    private lateinit var binding: ActivityOrderConfirmBinding
    private lateinit var cartItems: List<CartItem>
    private var totalAmount: Double = 0.0
    private var customerId: String? = null
    private var shopId: String? = null
    private var shopName: String = "Shop"

    private val paymentOptions = listOf("Cash", "Card", "UPI")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOrderConfirmBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Load session & intent data
        customerId = SessionManager.getCustomerId(this)
        shopId = intent.getStringExtra("SHOP_ID") ?: SessionManager.getShopId(this)
        shopName = SessionManager.getShopName(this) ?: "Shop"

        if (customerId.isNullOrEmpty() || shopId.isNullOrEmpty()) {
            Toast.makeText(this, "Session expired. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        // Get cart items and total from intent or CartManager
        cartItems = intent.getParcelableArrayListExtra("cart") ?: CartManager.getCart(shopId!!)
        totalAmount = intent.getDoubleExtra("total", 0.0)

        if (cartItems.isEmpty()) {
            Toast.makeText(this, "Cart is empty", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        // Show total & shop name
        binding.textViewTotal.text = "Total: ₹%.2f".format(totalAmount)
        binding.textViewShopName.text = "Shop: $shopName"

        // Setup payment spinner
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, paymentOptions)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        binding.paymentSpinner.adapter = adapter

        // Disable order button until payment selected
        binding.buttonPlaceOrder.isEnabled = false
        binding.paymentSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>, view: View?, position: Int, id: Long) {
                binding.buttonPlaceOrder.isEnabled = true
            }

            override fun onNothingSelected(parent: AdapterView<*>) {
                binding.buttonPlaceOrder.isEnabled = false
            }
        }

        binding.buttonPlaceOrder.setOnClickListener {
            val selectedPayment = binding.paymentSpinner.selectedItem.toString()
            if (selectedPayment.isEmpty()) {
                Toast.makeText(this, "Please select a payment method", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            // Confirm payment dialog
            AlertDialog.Builder(this)
                .setTitle("Confirm Payment")
                .setMessage("Proceed with payment of ₹%.2f using $selectedPayment?".format(totalAmount))
                .setPositiveButton("Pay") { _, _ ->
                    placeOrder(selectedPayment)
                }
                .setNegativeButton("Cancel", null)
                .show()
        }
    }

    private fun placeOrder(paymentMethod: String) {
        val apiService = RetrofitClient.getInstance(this).create(ApiService::class.java)

        val itemsList = cartItems.map { item ->
            OrderItemRequest(
                item_id = item.item.id,
                quantity = item.quantity
            )
        }

        val orderData = CreateOrderRequest(
            shopId = shopId!!,
            payment_method = paymentMethod,
            items = itemsList
        )

        // Call backend API
        apiService.createOrder(orderData).enqueue(object : Callback<Map<String, Any>> {
            override fun onResponse(call: Call<Map<String, Any>>, response: Response<Map<String, Any>>) {
                if (response.isSuccessful) {
                    Toast.makeText(this@OrderConfirmActivity, "Order placed successfully!", Toast.LENGTH_SHORT).show()
                    CartManager.clearCart(shopId!!)

                    // Go to Thank You screen
                    val intent = Intent(this@OrderConfirmActivity, ThankYouActivity::class.java)
                    intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
                    startActivity(intent)
                    finish()
                } else {
                    Toast.makeText(this@OrderConfirmActivity, "Failed to place order. Try again!", Toast.LENGTH_LONG).show()
                }
            }

            override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
                Toast.makeText(this@OrderConfirmActivity, "Network error: ${t.message}", Toast.LENGTH_LONG).show()
            }
        })
    }
}
