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
        val shopData = hashMapOf(
            "shop_id" to shopId,
            "name" to shopName,
            "shopkeeper_id" to shopkeeperId
        )

        // 1️⃣ Save shop in "shops" collection
        db.collection("shops")
            .add(shopData)
            .addOnSuccessListener { documentRef ->
                // 2️⃣ Update SessionManager
                SessionManager.setShopInfo(this, shopId.toString(), shopName)

                // 3️⃣ Update the user document to mark shopExists = true
                db.collection("users")
                    .whereEqualTo("shopkeeperId", shopkeeperId)
                    .get()
                    .addOnSuccessListener { querySnapshot ->
                        if (!querySnapshot.isEmpty) {
                            val userDoc = querySnapshot.documents[0]
                            val userRef = db.collection("users").document(userDoc.id)
                            userRef.update(
                                mapOf(
                                    "shopExists" to true,
                                    "shop" to mapOf(
                                        "id" to shopId.toString(),
                                        "name" to shopName
                                    )
                                )
                            )
                        }
                    }

                Toast.makeText(this, "Shop created!", Toast.LENGTH_SHORT).show()

                // Redirect to AddItemsActivity
                val intent = Intent(this, AddItemsActivity::class.java)
                startActivity(intent)
                finish()
            }
            .addOnFailureListener {
                Toast.makeText(this, "Error saving shop", Toast.LENGTH_SHORT).show()
            }
    }}

