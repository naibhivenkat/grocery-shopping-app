package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.adapters.ItemAdapter
import com.example.groceryshoppingapp.models.CartItem
import com.google.android.material.floatingactionbutton.FloatingActionButton
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager

class CustomerItemsActivity : AppCompatActivity() {

    private lateinit var recyclerView: RecyclerView
    private lateinit var itemAdapter: ItemAdapter
    private lateinit var fabCart: FloatingActionButton

    private var shopId: String? = null
    private var customerId:  String? = null
    private val cartItems = mutableListOf<CartItem>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_customer_items)

        recyclerView = findViewById(R.id.recyclerView)
        fabCart = findViewById(R.id.fabCart)

        // ✅ Load session data instead of intent extras
        customerId = SessionManager.getCustomerId(this)
        shopId = SessionManager.getShopId(this)

        if (customerId.isNullOrEmpty() || shopId.isNullOrEmpty()) {
            Toast.makeText(this, "Session expired. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }


        recyclerView.layoutManager = LinearLayoutManager(this)

        itemAdapter = ItemAdapter { item -> addToCart(item) }
        recyclerView.adapter = itemAdapter

        fetchItems()

        fabCart.setOnClickListener {
            val intent = Intent(this, CartActivity::class.java)
            startActivity(intent)
        }

    }

    private fun fetchItems() {
        val sid = shopId ?: return
        val items = SampleData.getItemsForShop(sid)
        itemAdapter.updateItems(items)
    }


    private fun addToCart(item: Item) {
        val sid = shopId ?: return  // ✅ prevent crash if null
        CartManager.addToCart(item, sid)
        Toast.makeText(this, "${item.name} added to cart", Toast.LENGTH_SHORT).show()
    }


}
