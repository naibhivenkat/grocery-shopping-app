package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.network.ApiClient
import com.example.groceryshoppingapp.utils.SessionManager
import org.json.JSONArray
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import com.example.groceryshoppingapp.network.ApiResponse
import com.example.groceryshoppingapp.models.Item

class AddItemsActivity : AppCompatActivity() {

    private lateinit var etItemName: EditText
    private lateinit var etItemPrice: EditText
    private lateinit var etItemQuantity: EditText
    private lateinit var etItemDescription: EditText
    private lateinit var btnAddItem: Button
    private lateinit var btnFinish: Button
    private lateinit var listViewItems: ListView

    private val itemDataList = mutableListOf<JSONObject>()

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

        val shopId = SessionManager.getShopId(this)

        btnAddItem.setOnClickListener {
            val name = etItemName.text.toString().trim()
            val price = etItemPrice.text.toString().trim()
            val stock = etItemQuantity.text.toString().trim()
            val description = etItemDescription.text.toString().trim()

            if (name.isEmpty() || price.isEmpty() || stock.isEmpty() || description.isEmpty()) {
                Toast.makeText(this, "Please fill all fields", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val item = JSONObject().apply {
                put("name", name)
                put("price", price)
                put("stock_quantity", stock)
                put("description", description)
            }
            itemDataList.add(item)

            val displayList = itemDataList.map { json ->
                val displayStock = when {
                    json.has("stock_quantity") -> json.optString("stock_quantity", "0")
                    json.has("stock") -> json.optString("stock", "0")
                    else -> "0"
                }
                "Name: ${json.optString("name", "")} | Price: ₹${json.optString("price", "")} | Stock: $displayStock | Desc: ${json.optString("description", "")}"
            }

            val adapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, displayList)
            listViewItems.adapter = adapter

            etItemName.text.clear()
            etItemPrice.text.clear()
            etItemQuantity.text.clear()
            etItemDescription.text.clear()
        }

        btnFinish.setOnClickListener {
            if (itemDataList.isEmpty()) {
                Toast.makeText(this, "No items to save", Toast.LENGTH_SHORT).show()
            } else {
                // Convert list of JSONObjects → JSONArray
                val jsonArray = JSONArray(itemDataList)
                sendItemsToBackend(jsonArray)
            }
        }
    }

    private fun sendItemsToBackend(items: JSONArray) {
        val token = SessionManager.getAuthToken(this) ?: ""
        val shopId = SessionManager.getShopId(this) ?: ""

        if (token.isEmpty() || shopId.isEmpty()) {
            Toast.makeText(this, "Missing auth token or shop ID", Toast.LENGTH_SHORT).show()
            return
        }

        // Convert JSONArray → List<Item>
        val itemsList = (0 until items.length()).map { i ->
            val json = items.getJSONObject(i)
            Item(
                id = "", // backend can assign ID
                name = json.optString("name"),
                price = json.optString("price").toDoubleOrNull() ?: 0.0,
                stockQuantity = json.optString("stock_quantity").toIntOrNull() ?: 0,
                description = json.optString("description"),
                shopid = shopId,
                imageUrl = null
            )
        }

        // API call
        val call = ApiClient.apiService.addItems("Bearer $token", shopId, itemsList)
        call.enqueue(object : Callback<ApiResponse> {
            override fun onResponse(call: Call<ApiResponse>, response: Response<ApiResponse>) {
                if (response.isSuccessful && response.body()?.success == true) {
                    Toast.makeText(this@AddItemsActivity, "Items added successfully!", Toast.LENGTH_SHORT).show()
                    SessionManager.setHasItemsAdded(this@AddItemsActivity, true)
                    finish() // close activity
                } else {
                    Toast.makeText(this@AddItemsActivity, "Failed to add items", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<ApiResponse>, t: Throwable) {
                Toast.makeText(this@AddItemsActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }



}
