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
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager

class OrderConfirmActivity : AppCompatActivity() {

    private lateinit var binding: ActivityOrderConfirmBinding
    private lateinit var cartItems: List<CartItem>
    private var totalAmount: Double = 0.0
    private var customerId: String? = null
    private var shopId: String? = null
    private var shopName = String

    private val paymentOptions = listOf("Cash", "Card", "UPI")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityOrderConfirmBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Load session data
        customerId = SessionManager.getCustomerId(this)
        shopId = intent.getStringExtra("SHOP_ID") ?: SessionManager.getShopId(this)

        if (customerId.isNullOrEmpty() || shopId.isNullOrEmpty()) {
            Toast.makeText(this, "Session expired. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        // Get cart and total from intent or fallback
        val safeShopId = shopId!!
        cartItems = intent.getParcelableArrayListExtra("cart") ?: CartManager.getCart(safeShopId)
        totalAmount = intent.getDoubleExtra("total", 0.0)

        if (cartItems.isEmpty()) {
            Toast.makeText(this, "Cart is empty", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        binding.textViewTotal.text = "Total: ₹%.2f".format(totalAmount)

        // Setup payment spinner
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, paymentOptions)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        binding.paymentSpinner.adapter = adapter

        // Optional: Disable order button until a selection is made
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
            val selectedPayment = binding.paymentSpinner.selectedItem?.toString() ?: run {
                Toast.makeText(this, "Please select a payment method", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            AlertDialog.Builder(this)
                .setTitle("Confirm Payment")
                .setMessage("Proceed with payment using $selectedPayment?")
                .setPositiveButton("Proceed") { _, _ ->
                    // ✅ Save shop info into session
                    SessionManager.setShopInfo(this, shopId.toString(), SessionManager.getShopName(this) ?: "Shop")

                    Toast.makeText(this, "Order placed using $selectedPayment!", Toast.LENGTH_SHORT).show()
                    val intent = Intent(this, OrderSummaryActivity::class.java).apply {
                        putParcelableArrayListExtra("cart", ArrayList(cartItems))
                        putExtra("payment", selectedPayment)
                        putExtra("total", totalAmount)
                        putExtra("shop_id", shopId)
                        putExtra("customer_id", customerId)
                    }
                    startActivity(intent)
                    finish()
                }
                .setNegativeButton("Cancel", null)
                .setNeutralButton("Change Payment Method", null)
                .show()
        }

    }
}
