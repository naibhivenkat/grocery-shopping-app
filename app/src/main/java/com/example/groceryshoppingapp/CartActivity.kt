package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
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

        shopId = SessionManager.getShopId(this) ?: ""
        if (shopId.isEmpty()) {
            Toast.makeText(this, "Invalid shop selected", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        recyclerViewCart = findViewById(R.id.recyclerViewCart)
        totalTextView = findViewById(R.id.textViewTotal)
        placeOrderButton = findViewById(R.id.buttonConfirmOrder)
        backToShopButton = findViewById(R.id.buttonBackToShop)

        recyclerViewCart.layoutManager = LinearLayoutManager(this)

        cartItems = CartManager.getCart(shopId).toMutableList()

        cartAdapter = CartAdapter(this, cartItems) {
            updateTotal()
        }

        recyclerViewCart.adapter = cartAdapter

        updateTotal()

        placeOrderButton.setOnClickListener {
            if (cartItems.isEmpty()) {
                Toast.makeText(this, "Cart is empty!", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            showConfirmOrderDialog()
        }

        backToShopButton.setOnClickListener {
            val intent = Intent(this, ShopItemsActivity::class.java)
            intent.putExtra("SHOP_ID", shopId) // ✅ Use "SHOP_ID" as expected by ShopItemsActivity
            intent.putExtra("SHOP_NAME", SampleData.getShopNameById(shopId)) // ✅ add this too
            startActivity(intent)
            finish()
        }
    }

    private fun updateTotal() {
        val total = cartItems.sumOf { it.item.price * it.quantity }
        totalTextView.text = "Total: ₹%.2f".format(total)

        if (cartItems.isEmpty()) {
            Toast.makeText(this, "Cart is now empty", Toast.LENGTH_SHORT).show()
            finish()
        }
    }

    private fun showConfirmOrderDialog() {
        val total = cartItems.sumOf { it.item.price * it.quantity }

        val itemDetails = cartItems.joinToString("\n") {
            "${it.item.name} x ${it.quantity} = ₹${"%.2f".format(it.item.price * it.quantity)}"
        }

        val shopName = SampleData.getShopNameById(shopId)
        val shopInfo = "Shop: $shopName"

        val message = "$shopInfo\n\n$itemDetails\n\nTotal: ₹${"%.2f".format(total)}"

        AlertDialog.Builder(this)
            .setTitle("Confirm Your Order")
            .setMessage(message)
            .setPositiveButton("Proceed") { _, _ ->
                val intent = Intent(this, OrderConfirmActivity::class.java)
                intent.putExtra("shopId", shopId)
                intent.putExtra("total", total)
                startActivity(intent)
            }
            .setNeutralButton("Update Cart") { dialog, _ ->
                dialog.dismiss()
            }
            .setNegativeButton("Cancel") { dialog, _ ->
                dialog.dismiss()
            }
            .show()
    }

    private fun placeOrder() {
        CartManager.clearCart(shopId)
        cartItems.clear()
        cartAdapter.notifyDataSetChanged()
        updateTotal()

        Toast.makeText(this, "Order placed successfully!", Toast.LENGTH_LONG).show()

        startActivity(Intent(this, CartShopListActivity::class.java))
        finish()
    }
}
