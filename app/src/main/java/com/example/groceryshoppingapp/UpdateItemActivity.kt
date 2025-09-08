package com.example.groceryshoppingapp

import android.os.Bundle
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.models.Item
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.network.ApiService
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class UpdateItemActivity : AppCompatActivity() {

    private lateinit var etName: EditText
    private lateinit var etPrice: EditText
    private lateinit var etQuantity: EditText
    private lateinit var etDescription: EditText
    private lateinit var btnUpdate: Button
    private lateinit var btnDelete: Button
    private lateinit var btnBack: ImageButton

    private var itemId: String? = null
    private val api = RetrofitClient.getInstance(this).create(ApiService::class.java)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_update_item)

        etName = findViewById(R.id.etItemName)
        etPrice = findViewById(R.id.etItemPrice)
        etQuantity = findViewById(R.id.etItemQuantity)
        etDescription = findViewById(R.id.etItemDescription)
        btnUpdate = findViewById(R.id.btnUpdateItem)
        btnDelete = findViewById(R.id.btnDeleteItem)
        btnBack = findViewById(R.id.btnBack)

        // Get item details from intent
        val item = intent.getParcelableExtra<Item>("item")
        if (item != null) {
            itemId = item.id
            etName.setText(item.name)
            etPrice.setText(item.price.toString())
            etQuantity.setText(item.stockQuantity.toString())
            etDescription.setText(item.description ?: "")
        } else {
            Toast.makeText(this, "Item data missing", Toast.LENGTH_SHORT).show()
            finish()
        }


        btnUpdate.setOnClickListener {
            updateItem()
        }

        btnDelete.setOnClickListener {
            deleteItem()
        }

        btnBack.setOnClickListener {
            finish()
        }
    }

    private fun updateItem() {
        val name = etName.text.toString()
        val price = etPrice.text.toString()
        val quantity = etQuantity.text.toString()
        val description = etDescription.text.toString()

        if (name.isEmpty() || price.isEmpty() || quantity.isEmpty()) {
            Toast.makeText(this, "Fill all required fields", Toast.LENGTH_SHORT).show()
            return
        }

        val data = mapOf(
            "name" to name,
            "price" to price,
            "quantity" to quantity,
            "description" to description
        )

        api.updateItem(itemId!!, data).enqueue(object : Callback<Map<String, Boolean>> {
            override fun onResponse(call: Call<Map<String, Boolean>>, response: Response<Map<String, Boolean>>) {
                if (response.isSuccessful && response.body()?.get("success") == true) {
                    Toast.makeText(this@UpdateItemActivity, "Item updated", Toast.LENGTH_SHORT).show()
                    finish()
                } else {
                    Toast.makeText(this@UpdateItemActivity, "Update failed", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<Map<String, Boolean>>, t: Throwable) {
                Toast.makeText(this@UpdateItemActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun deleteItem() {
        api.deleteItem(itemId!!).enqueue(object : Callback<Map<String, Boolean>> {
            override fun onResponse(call: Call<Map<String, Boolean>>, response: Response<Map<String, Boolean>>) {
                if (response.isSuccessful && response.body()?.get("success") == true) {
                    Toast.makeText(this@UpdateItemActivity, "Item deleted", Toast.LENGTH_SHORT).show()
                    finish()
                } else {
                    Toast.makeText(this@UpdateItemActivity, "Delete failed", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<Map<String, Boolean>>, t: Throwable) {
                Toast.makeText(this@UpdateItemActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }
}
