package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.databinding.ActivityOrderSummaryBinding
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.utils.SessionManager
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
            Toast.makeText(this, "Session expired. Please log in again.", Toast.LENGTH_LONG).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val formattedTime = SimpleDateFormat("dd MMM yyyy, hh:mm a", Locale.getDefault()).format(Date())

        binding.textViewShopName.text = "Shop: $shopName"
        binding.textViewPayment.text = "Payment: $paymentMethod"
        binding.textViewOrderTime.text = "Time: $formattedTime"
        binding.textViewTotal.text = "Total: ₹%.2f".format(totalAmount)

        binding.orderItems.text = cartItems.joinToString("\n") {
            "${it.item.name} - ₹${it.item.price} x ${it.quantity} = ₹%.2f".format(
                it.item.price * it.quantity
            )
        }

        binding.buttonCancel.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Cancel Order")
                .setMessage("Cancel this order?")
                .setPositiveButton("Yes") { _, _ -> finish() }
                .setNegativeButton("No", null)
                .show()
        }

        binding.buttonModify.setOnClickListener {
            val intent = Intent(this, OrderConfirmActivity::class.java)
            intent.putParcelableArrayListExtra("cart", ArrayList(cartItems))
            intent.putExtra("total", totalAmount)
            startActivity(intent)
            finish()
        }

        binding.buttonConfirmFinal.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Confirm Order")
                .setMessage("Proceed to payment?")
                .setPositiveButton("Confirm") { _, _ ->
                    goBackToOrderConfirm()
                }
                .setNegativeButton("Cancel", null)
                .show()
        }
    }

    private fun goBackToOrderConfirm() {
        val intent = Intent(this, OrderConfirmActivity::class.java)
        intent.putParcelableArrayListExtra("cart", ArrayList(cartItems))
        intent.putExtra("total", totalAmount)
        intent.putExtra("payment", paymentMethod)
        startActivity(intent)
        finish()
    }
}
