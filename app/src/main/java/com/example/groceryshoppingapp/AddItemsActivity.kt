package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.models.AddItemsRequest
import com.example.groceryshoppingapp.network.ApiClient
import com.example.groceryshoppingapp.network.ApiResponse
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class AddItemsActivity : AppCompatActivity() {

    private lateinit var etItemName: EditText
    private lateinit var etItemPrice: EditText
    private lateinit var etItemQuantity: EditText
    private lateinit var etItemDescription: EditText
    private lateinit var btnAddItem: Button
    private lateinit var btnFinish: Button
    private lateinit var listViewItems: ListView

    private val itemDataList = mutableListOf<Item>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_add_items)

        etItemName = findViewById(R.id.etItemName)
        etItemPrice = findViewById(R.id.etItemPrice)
        etItemQuantity = findViewById(R.id.etItemQuantity)
        etItemDescription = findViewById(R.id.etItemDescription)
        btnAddItem = findViewById(R.id.btnAddItem)
        btnFinish = findViewById(R.id.btnFinish)
        listViewItems = findViewById(R.id.listViewItems)

        btnAddItem.setOnClickListener { addItemToList() }
        btnFinish.setOnClickListener { finishAddingItems() }
    }

    private fun addItemToList() {
        val name = etItemName.text.toString().trim()
        val price = etItemPrice.text.toString().trim()
        val stock = etItemQuantity.text.toString().trim()
        val description = etItemDescription.text.toString().trim()

        if (name.isEmpty() || price.isEmpty() || stock.isEmpty() || description.isEmpty()) {
            Toast.makeText(this, "Please fill all fields", Toast.LENGTH_SHORT).show()
            return
        }

        val shopId = SessionManager.getShopId(this)
        if (shopId.isNullOrEmpty()) {
            Toast.makeText(this, "Shop ID missing. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val item = Item(
            id = "", // backend generates ID
            name = name,
            price = price.toDoubleOrNull() ?: 0.0,
            stockQuantity = stock.toIntOrNull() ?: 0,
            description = description,
            shopid = shopId,
            imageUrl = null
        )

        itemDataList.add(item)

        // Update ListView
        val displayList = itemDataList.map {
            "Name: ${it.name} | Price: ₹${it.price} | Stock: ${it.stockQuantity} | Desc: ${it.description}"
        }
        listViewItems.adapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, displayList)

        // Clear input fields
        etItemName.text.clear()
        etItemPrice.text.clear()
        etItemQuantity.text.clear()
        etItemDescription.text.clear()
    }

    private fun finishAddingItems() {
        if (itemDataList.isEmpty()) {
            Toast.makeText(this, "No items to save", Toast.LENGTH_SHORT).show()
            return
        }

        val token = SessionManager.getAuthToken(this)
        val shopId = SessionManager.getShopId(this)

        if (token.isNullOrEmpty() || shopId.isNullOrEmpty()) {
            Toast.makeText(this, "❌ Missing auth token or shop ID. Please login again.", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }

        val request = AddItemsRequest(shopId, itemDataList)
        //ApiClient.apiService.addItems("Bearer $token", request)
        val authHeader = "Bearer $token"
        ApiClient.apiService.addItems(authHeader, request)
            .enqueue(object : Callback<ApiResponse> {
                override fun onResponse(call: Call<ApiResponse>, response: Response<ApiResponse>) {
                    if (response.isSuccessful && response.body()?.success == true) {
                        Toast.makeText(this@AddItemsActivity, "✅ Items added successfully!", Toast.LENGTH_SHORT).show()
                        SessionManager.setHasItemsAdded(this@AddItemsActivity, true)
                        startActivity(Intent(this@AddItemsActivity, ShopOwnerMainActivity::class.java))
                        finish()
                    } else {
                        Toast.makeText(this@AddItemsActivity, "❌ Failed: ${response.body()?.message ?: "Unknown error"}", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
                    Toast.makeText(this@AddItemsActivity, "⚠️ Error: ${t.message ?: "Unknown error"}", Toast.LENGTH_SHORT).show()
                }
            })
    }
}
