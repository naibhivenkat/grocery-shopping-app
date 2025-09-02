package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.firebase.firestore.FirebaseFirestore

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
                generateShopIdAndCreate(shopName)
            }
        }
    }

    private fun generateShopIdAndCreate(shopName: String) {
        db.collection("shops")
            .get()
            .addOnSuccessListener { result ->
                var maxId = 0
                for (doc in result) {
                    val shopId = doc.getLong("shop_id")?.toInt() ?: 0
                    if (shopId > maxId) maxId = shopId
                }

                val newShopId = maxId + 1
                saveShopToFirebase(newShopId, shopName)
            }
            .addOnFailureListener {
                Toast.makeText(this, "Error generating shop ID", Toast.LENGTH_SHORT).show()
            }
    }

    private fun saveShopToFirebase(shopId: Int, shopName: String) {
        val shopkeeperId = SessionManager.getShopkeeperId(this)
        if (shopkeeperId.isNullOrEmpty()) {
            Toast.makeText(
                this,
                "Error: Shopkeeper ID missing. Please login again.",
                Toast.LENGTH_SHORT
            ).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val shopData = hashMapOf(
            "shop_id" to shopId,
            "name" to shopName,
            "shopkeeper_id" to shopkeeperId
        )

        db.collection("shops")
            .add(shopData)
            .addOnSuccessListener { _ ->

                // ✅ Save shop_id in SessionManager
                val shopIdStr = shopId.toString()
                SessionManager.setShopId(this, shopIdStr)
                SessionManager.setShopInfo(this, shopIdStr, shopName)

                // ✅ Preserve auth token (important for AddItemsActivity)
                val token = SessionManager.getAuthToken(this)
                if (!token.isNullOrEmpty()) {
                    SessionManager.setAuthToken(this, token) // refresh same token
                }

                // ✅ Update user's shopExists in Firestore
                db.collection("users")
                    .whereEqualTo("shopkeeperId", shopkeeperId)
                    .get()
                    .addOnSuccessListener { snapshot ->
                        if (!snapshot.isEmpty) {
                            val userDoc = snapshot.documents[0]
                            db.collection("users").document(userDoc.id)
                                .update(
                                    "shopExists", true,
                                    "shop", mapOf("id" to shopIdStr, "name" to shopName)
                                )
                        }
                    }

                Toast.makeText(this, "Shop created!", Toast.LENGTH_SHORT).show()

                // ✅ Go to AddItemsActivity
                startActivity(Intent(this, AddItemsActivity::class.java))
                finish()
            }
            .addOnFailureListener {
                Toast.makeText(this, "Error saving shop", Toast.LENGTH_SHORT).show()
            }
    }
}
