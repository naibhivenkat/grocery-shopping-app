package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.firebase.firestore.FirebaseFirestore
import java.util.UUID

class CreateShopActivity : AppCompatActivity() {

    private lateinit var etShopName: EditText
    private lateinit var btnCreateShop: Button
    private lateinit var db: FirebaseFirestore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_create_shop)

        db = FirebaseFirestore.getInstance()

        etShopName = findViewById(R.id.etShopName)
        btnCreateShop = findViewById(R.id.btnCreateShop)

        btnCreateShop.setOnClickListener {
            val shopName = etShopName.text.toString().trim()
            if (shopName.isEmpty()) {
                Toast.makeText(this, "Enter shop name", Toast.LENGTH_SHORT).show()
            } else {
                createShop(shopName)
            }
        }
    }

    private fun createShop(shopName: String) {
        val shopkeeperId = SessionManager.getShopkeeperId(this)
        if (shopkeeperId.isNullOrEmpty()) {
            Toast.makeText(this, "Error: Shopkeeper ID missing. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        // 🔑 Generate UUID instead of incremental IDs
        val newShopId = UUID.randomUUID().toString()

        val shopData = hashMapOf(
            "id" to newShopId,          // ✅ backend expects "id"
            "name" to shopName,
            "shopkeeper_id" to shopkeeperId
        )

        db.collection("shops")
            .add(shopData)
            .addOnSuccessListener { _ ->

                // Save locally in SessionManager
                SessionManager.setShopId(this, newShopId)
                SessionManager.setShopInfo(this, newShopId, shopName)

                // Preserve token if available
                val token = SessionManager.getAuthToken(this)
                if (!token.isNullOrEmpty()) {
                    SessionManager.setAuthToken(this, token)
                }

                // Update user document → attach shop
                db.collection("users")
                    .whereEqualTo("shopkeeperId", shopkeeperId)
                    .get()
                    .addOnSuccessListener { snapshot ->
                        if (!snapshot.isEmpty) {
                            val userDoc = snapshot.documents[0]
                            db.collection("users").document(userDoc.id)
                                .update(
                                    "shopExists", true,
                                    "shop", mapOf("id" to newShopId, "name" to shopName)
                                )
                        }
                    }

                Toast.makeText(this, "Shop created!", Toast.LENGTH_SHORT).show()
                startActivity(Intent(this, AddItemsActivity::class.java))
                finish()
            }
            .addOnFailureListener {
                Toast.makeText(this, "Error saving shop", Toast.LENGTH_SHORT).show()
            }
    }
}
