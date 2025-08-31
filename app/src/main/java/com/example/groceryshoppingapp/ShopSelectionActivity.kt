package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.AdapterView
import android.widget.Button
import android.widget.ListView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.adapters.ShopAdapter
import com.example.groceryshoppingapp.models.Shop
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager

class ShopSelectionActivity : AppCompatActivity() {

    private lateinit var shopListView: ListView
    private lateinit var shops: List<Shop>
    private var customerId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_shop_selection)

        shopListView = findViewById(R.id.shop_list_view)
        customerId = SessionManager.getCustomerId(this)

        if (customerId.isNullOrEmpty()) {
            Toast.makeText(this, "Invalid customer ID", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        // Sample shops (you can later load from server/db)
        shops = SampleData.getShops()
        val adapter = ShopAdapter(this, shops)
        shopListView.adapter = adapter

        shopListView.onItemClickListener = AdapterView.OnItemClickListener { _, _, position, _ ->
            val selectedShop = shops[position]

            val dialog = androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle("Confirm Shop")
                .setMessage("Do you want to continue with '${selectedShop.name}'?")
                .setPositiveButton("OK") { _, _ ->
                    val intent = Intent(this, ShopItemsActivity::class.java).apply {
                        putExtra("SHOP_ID", selectedShop.id)
                        putExtra("SHOP_NAME", selectedShop.name)
                        putExtra("customer_id", customerId)
                    }
                    startActivity(intent)
                }
                .setNegativeButton("Cancel", null)
                .create()
            dialog.show()
        }

        // ✅ Buttons
        val btnHome: Button = findViewById(R.id.btn_home)
        val btnBack: Button = findViewById(R.id.btn_back)
        val btnCart: Button = findViewById(R.id.btn_cart)

        btnHome.setOnClickListener {
            val intent = Intent(this, CustomerHomeActivity::class.java)
            intent.putExtra("customer_id", customerId)
            startActivity(intent)
            finish()
        }

        btnBack.setOnClickListener {
            finish()
        }

        btnCart.setOnClickListener {
            val allCarts = CartManager.getAllCarts().filterValues { it.isNotEmpty() }

            if (allCarts.isEmpty()) {
                Toast.makeText(this, "Cart is empty", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val shopIdList = allCarts.keys.toList()
            val shopNames = shopIdList.map { shopId ->
                shops.find { it.id == shopId }?.name ?: "Shop $shopId"
            }.toTypedArray()

            // Show a dialog to pick one shop cart
            val dialog = androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle("Select Cart (Shop)")
                .setItems(shopNames) { _, index ->
                    val selectedShopId = shopIdList[index]
                    val selectedCartItems = allCarts[selectedShopId] ?: emptyList()

                    val intent = Intent(this, CartActivity::class.java).apply {
                        putExtra("customer_id", customerId)
                        putExtra("shop_id", selectedShopId)
                        putParcelableArrayListExtra("cart_items", ArrayList(selectedCartItems))
                    }
                    startActivity(intent)
                }
                .setNegativeButton("Cancel", null)
                .create()
            dialog.show()
        }
    }
}
