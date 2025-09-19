package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.CartAdapter
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager

class CartActivity : AppCompatActivity() {

    private lateinit var recyclerViewCart: RecyclerView
    private lateinit var totalTextView: TextView
    private lateinit var placeOrderButton: Button
    private lateinit var backToShopButton: Button
    private var shopId: String = ""
    private lateinit var cartItems: MutableList<CartItem>
    private lateinit var cartAdapter: CartAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_cart)

        // Get shopId from intent or session
        shopId = intent.getStringExtra("SHOP_ID") ?: SessionManager.getShopId(this) ?: ""
       // Log.d("CartActivity", "Loaded with shopId=$shopId")

        // Get shopId from intent or session
        //shopId = intent.getStringExtra("SHOP_ID") ?: SessionManager.getShopId(this)

        if (shopId.isNullOrEmpty()) {
            Toast.makeText(this, "Please select a shop first.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, ShopSelectionActivity::class.java))
            finish()
            return
        }


        recyclerViewCart = findViewById(R.id.recyclerViewCart)
        totalTextView = findViewById(R.id.textViewTotal)
        placeOrderButton = findViewById(R.id.buttonConfirmOrder)
        backToShopButton = findViewById(R.id.buttonBackToShop)

        recyclerViewCart.layoutManager = LinearLayoutManager(this)

        // Load items from CartManager
        cartItems = CartManager.getCart(shopId).toMutableList()
        Log.d("CartActivity", "Loaded ${cartItems.size} items from CartManager for shopId=$shopId")

        cartAdapter = CartAdapter(this, cartItems) {
            updateTotal()
        }
        recyclerViewCart.adapter = cartAdapter

        updateTotal()

        placeOrderButton.setOnClickListener {
            if (cartItems.isEmpty()) {
                Toast.makeText(this, "Cart is empty!", Toast.LENGTH_SHORT).show()
                Log.w("CartActivity", "Place order clicked but cart empty")
                return@setOnClickListener
            }
            showConfirmOrderDialog()
        }

        backToShopButton.setOnClickListener {
            val intent = Intent(this, CustomerItemsActivity::class.java)
            intent.putExtra("SHOP_ID", shopId)
            startActivity(intent)
            finish()
        }
    }

    private fun updateTotal() {
        val total = cartItems.sumOf { it.item.price * it.quantity }
        totalTextView.text = "Total: ₹%.2f".format(total)
        Log.d("CartActivity", "Cart updated → total=$total, items=${cartItems.size}")
    }

    private fun showConfirmOrderDialog() {
        val total = cartItems.sumOf { it.item.price * it.quantity }

        val itemDetails = cartItems.joinToString("\n") {
            "${it.item.name} x ${it.quantity} = ₹${"%.2f".format(it.item.price * it.quantity)}"
        }

        val message = "Shop ID: $shopId\n\n$itemDetails\n\nTotal: ₹${"%.2f".format(total)}"

        AlertDialog.Builder(this)
            .setTitle("Confirm Your Order")
            .setMessage(message)
            .setPositiveButton("Proceed") { _, _ ->
                Log.d("CartActivity", "Proceeding to OrderConfirmActivity with shopId=$shopId")
                val intent = Intent(this, OrderConfirmActivity::class.java)
                intent.putExtra("SHOP_ID", shopId)
                intent.putExtra("total", total)
                startActivity(intent)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }
}
