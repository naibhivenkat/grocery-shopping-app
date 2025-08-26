package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.utils.SessionManager
class CustomerActivity : AppCompatActivity() {

    private lateinit var browseShopsButton: Button
    private lateinit var viewCartButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_customer)

        browseShopsButton = findViewById(R.id.btn_browse_shops)
        viewCartButton = findViewById(R.id.btn_view_cart)

        browseShopsButton.setOnClickListener {
            val intent = Intent(this, CustomerHomeActivity::class.java)
            startActivity(intent)
        }

        viewCartButton.setOnClickListener {
            val shopId = SessionManager.getShopId(this)
            if (!shopId.isNullOrEmpty()) {
                val intent = Intent(this, CartActivity::class.java)
                intent.putExtra("SHOP_ID", shopId) // ✅ pass UUID string
                startActivity(intent)
            } else {
                Toast.makeText(this, "Please select a shop first.", Toast.LENGTH_SHORT).show()
            }
        }

    }}
