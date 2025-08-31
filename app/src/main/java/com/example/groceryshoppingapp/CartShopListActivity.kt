package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.adapters.ShopCartListAdapter
import com.example.groceryshoppingapp.databinding.ActivityCartShopListBinding
import com.example.groceryshoppingapp.models.CartItem
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import com.example.groceryshoppingapp.SampleData

class CartShopListActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCartShopListBinding
    private var customerId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityCartShopListBinding.inflate(layoutInflater)
        setContentView(binding.root)

        customerId = SessionManager.getCustomerId(this)
        if (customerId.isNullOrEmpty()) {
            Toast.makeText(this, "Session expired. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val allCarts = CartManager.getAllCarts()

        if (allCarts.isEmpty()) {
            Toast.makeText(this, "No carts found.", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        val shopList = allCarts.map { (shopId, cartItems) ->
            Triple(shopId, SampleData.getShopNameById(shopId) ?: "Unknown Shop", cartItems)
        }

        val adapter = ShopCartListAdapter(shopList) { shopId, cartItems ->
            val intent = Intent(this, CartActivity::class.java).apply {
                putExtra("SHOP_ID", shopId)
                putParcelableArrayListExtra("cart_items", ArrayList(cartItems))
            }
            SessionManager.setShopId(this, shopId)
            startActivity(intent)
        }

        binding.recyclerViewShopCarts.layoutManager = LinearLayoutManager(this)
        binding.recyclerViewShopCarts.adapter = adapter
    }
}
