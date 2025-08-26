package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.android.volley.toolbox.JsonObjectRequest
import com.android.volley.toolbox.Volley
import com.example.groceryshoppingapp.utils.SessionManager
import org.json.JSONArray
import org.json.JSONObject

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
                sendItemsToBackend(shopId, itemDataList)
            }
        }
    }

    private fun sendItemsToBackend(shopId: String?, items: List<JSONObject>) {
        val url = "https://grocery-shopping-app-yyqx.onrender.com/add_items"
        val requestQueue = Volley.newRequestQueue(this)

        val payload = JSONObject().apply {
            put("shop_id", shopId)
            put("items", JSONArray(items))
        }

        val request = object : JsonObjectRequest(
            Method.POST, url, payload,
            {
                // ✅ Save flag that items have been added
                SessionManager.setHasItemsAdded(this, true)

                Toast.makeText(this, "Items saved. Returning to dashboard.", Toast.LENGTH_SHORT).show()
                val intent = Intent(this, ShopOwnerDashboardActivity::class.java)
                intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                startActivity(intent)
            },
            { error ->
                Toast.makeText(this, "Failed to save items: ${error.message}", Toast.LENGTH_LONG).show()
            }
        ) {}

        requestQueue.add(request)
    }
}
